import argparse
import base64
import configparser
import json
import logging
import signal
import sys

import newspaper
import redis
import validators
from mastodon import Mastodon
from mastodon.Mastodon import MastodonVersionError
from newspaper.article import ArticleException
from pyail import PyAIL
from urlextract import URLExtract


logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s:%(message)s', level=logging.INFO, datefmt='%I:%M:%S')

# Parse the arguments
parser = argparse.ArgumentParser()
parser.add_argument("query", help="query to search on ActivityPub to feed AIL")
parser.add_argument("--verbose", help="verbose output", action="store_true")
parser.add_argument("--nocache", help="disable cache", action="store_true")
args = parser.parse_args()

# Initial setup
uuid = 'a4cfd483-86dc-4900-9fb9-5cd6027b5d04'
ailfeedertype = "ail-feeder-activitypub"
ailurlextract = "ail_feeder_urlextract"

config = configparser.ConfigParser()
config.read('etc/ail-feeder-activitypub.cfg')

if 'general' in config:
    uuid = config['general']['uuid']

if 'redis' in config:
    r = redis.Redis(host=config['redis']['host'], port=config['redis']['port'], db=config['redis']['db'])
else:
    r = redis.Redis()

if 'cache' in config:
    cache_expire = config['cache']['expire']
else:
    cache_expire = 86400

if 'ail' in config:
    ail_url = config['ail']['url']
    ail_key = config['ail']['apikey']
else:
    if args.verbose:
        logging.error("Ail section not found in the config file. Add it and the necessary fields and try again!")
    sys.exit(0)
try:
    pyail = PyAIL(ail_url, ail_key, ssl=False)
except Exception as e:
    logging.error(e)
    sys.exit(0)

# Get the ready instances from the file
with open('readyInstances.txt', 'r') as f:
    urls = f.readlines()
# Loop through them and scrape the data
for url in urls:
    url = url.replace('\n', '')
    if args.verbose:
        logging.info(url)
    # Register the app
    Mastodon.create_app(
         'pytooterapp',
         api_base_url = f'https://{url}',
         to_file = 'etc/pytooter_clientcred.secret'
    )
    # Then login
    mastodon = Mastodon(
        client_id = 'etc/pytooter_clientcred.secret',
        api_base_url = f'https://{url}'
    )
    with open('credentials.txt', 'r') as f:
        creds = f.readlines()
    mastodon.log_in(
        creds[0].replace('\n', ''),
        creds[1],
        to_file = 'etc/pytooter_usercred.secret'
    )
    wrongVersion = False
    # Try to connect to the instance, if it works, continue, otherwise skip it
    try:
        result = mastodon.search(args.query)
    # Sometimes an instances requires a different version, this is skipped in this case
    except MastodonVersionError:
        wrongVersion = True
        if args.verbose:
            logging.error("Wrong version!")
        continue
    if wrongVersion:
        continue
    
    # 3 fields will be the result of the request: accounts, hashtags and statuses
    # Loop through the accounts which match the query and extract the data
    for account in result['accounts']:
        if r.exists(f"c:{account['id']}"):
            if args.verbose:
                logging.info(f"Message {account['id']} already processed")
            if not args.nocache:
                continue
        else:
            r.set(f"c:{account['id']}", account['note'])
            r.expire(f"c:{account['id']}", cache_expire)

        a = {}

        a['source'] = ailfeedertype
        a['uuid'] = uuid
        a['default-encoding'] = 'UTF-8'

        a['meta'] = {}
        a['meta']['account:id'] = account['id']
        a['meta']['account:username'] = account['username']
        a['meta']['account:display_name'] = account['display_name']
        a['meta']['account:name'] = account['acct']
        if 'bot' in account:
            a['meta']['bot'] = account['bot']
        if 'group' in account:
            a['meta']['group'] = account['group']
        if 'discoverable' in account:
            a['meta']['discoverable'] = account['discoverable']
        a['meta']['created_at'] = account['created_at']
        a['meta']['bio'] = account['note']
        a['meta']['account:url'] = account['url']
        a['meta']['followers'] = account['followers_count']
        a['meta']['following'] = account['following_count']
        a['meta']['statuses'] = account['statuses_count']
        if 'last_status' in account:
            a['meta']['last_status'] = account['last_status_at']
        if 'emojis' in account:
            a['meta']['emojis'] = account['emojis']
        if 'fields' in account:
            a['meta']['fields'] = account['fields']
        if args.verbose:
            logging.info(json.dumps(a, indent=4, default=str))

        data = account['note']
        metadata = a['meta']
        pyail.feed_json_item(data, metadata, ailfeedertype, uuid)

        # Extract the URLs of the bio
        extractor = URLExtract()
        urls = extractor.find_urls(account['note'])
        for url in urls:
            # If the url is not valid, drop it and continue
            surl = url.split()[0]
            if not validators.url(surl):
                continue
        
            output = {}
            output['source'] = ailurlextract
            output['source-uuid'] = uuid
            output['default-encoding'] = 'UTF-8'

            output['meta'] = {}
            output['meta']['activitypub:account_id'] = account['id']

            output['meta']['activitypub:url-extracted'] = surl

            signal.alarm(10)
            try:
                article = newspaper.Article(surl)
            except TimeoutError:
                if args.verbose:
                    logging.error(f"Timeout reached for {surl}")
                continue
            else:
                signal.alarm(0)

            # Caching
            if r.exists(f"cu:{base64.b64encode(surl.encode())}"):
                if args.verbose:
                    logging.info(f"URL {surl} already processed")
                if not args.nocache:
                    continue
            else:
                r.set(f"cu:{base64.b64encode(surl.encode())}", account['note'])
                r.expire(f"cu:{base64.b64encode(surl.encode())}", cache_expire)
            
            if args.verbose:
                logging.info(f"Downloading and parsing {surl}")

            try:
                article.download()
                article.parse()
            except ArticleException:
                if args.verbose:
                    logging.error(f"Unable to download/parse {surl}")
                continue

            output['data'] = article.html

            nlpFailed = False

            try:
                article.nlp()
            except:
                if args.verbose:
                    logging.error(f"Unable to nlp {surl}")
                nlpFailed = True

                obj = json.dumps(output['data'], indent=4, sort_keys=True)

                if args.verbose:
                    logging.info("Uploading the URL to AIL...\n")
                pyail.feed_json_item(output['data'], output['meta'], ailurlextract, uuid)
                continue
        
            if nlpFailed:
                continue
            
            output['meta']['newspaper:text'] = article.text
            output['meta']['newspaper:authors'] = article.authors
            output['meta']['newspaper:keywords'] = article.keywords
            output['meta']['newspaper:publish_date'] = article.publish_date
            output['meta']['newspaper:top_image'] = article.top_image
            output['meta']['newspaper:movies'] = article.movies

            obj = json.dumps(output['data'], indent=4, sort_keys=True)
            if args.verbose:
                logging.info("Uploading the URL to AIL...\n")
            pyail.feed_json_item(output['data'], output['meta'], ailurlextract, uuid)


    # Loop through the hashtags and extract the data (in this case, there is no metadata available other than hashtag, date, usages on that day)
    # (there are always only the stats of the last 7 days available)
    # for hashtag in result['hashtags']:
    #     if args.verbose:
    #         logging.info(json.dumps(h, indent=4, default=str))

    # Loop through the statuses and extract the data
    for status in result['statuses']:
        s = {}

        s['source'] = ailfeedertype
        s['uuid'] = uuid
        s['default-encoding'] = 'UTF-8'
        
        s['meta'] = {}
        s['meta']['status:id'] = status['id']
        s['meta']['status:uri'] = status['uri']
        s['meta']['status:url'] = status['url']

        # Maybe extract only the necessary data from the account (see first loop)
        s['meta']['account'] = status['account']

        s['meta']['reply_to:id'] = status['in_reply_to_id']
        s['meta']['reply_to:account_id'] = status['in_reply_to_account_id']
        s['meta']['content'] = status['content']
        s['meta']['created'] = status['created_at']
        s['meta']['sensitive'] = status['sensitive']
        s['meta']['spoiler_text'] = status['spoiler_text']
        s['meta']['visibility'] = status['visibility']
        s['meta']['mentions'] = status['mentions']
        s['meta']['attachments'] = status['media_attachments']
        s['meta']['emojis'] = status['emojis']
        s['meta']['tags'] = status['tags']
        if args.verbose:
            logging.info(json.dumps(s, indent=4, default=str))

        data = status['content']
        metadata = s['meta']
        pyail.feed_json_item(data, metadata, ailfeedertype, uuid)

        # Extract the URLs of the bio
        extractor = URLExtract()
        urls = extractor.find_urls(status['content'])
        for url in urls:
            # If the url is not valid, drop it and continue
            surl = url.split()[0]
            if not validators.url(surl):
                continue
        
            output = {}
            output['source'] = ailurlextract
            output['source-uuid'] = uuid
            output['default-encoding'] = 'UTF-8'

            output['meta'] = {}
            output['meta']['activitypub:status_id'] = status['id']

            output['meta']['activitypub:url-extracted'] = surl

            signal.alarm(10)
            try:
                article = newspaper.Article(surl)
            except TimeoutError:
                if args.verbose:
                    logging.error(f"Timeout reached for {surl}")
                continue
            else:
                signal.alarm(0)

            # Caching
            if r.exists(f"cu:{base64.b64encode(surl.encode())}"):
                if args.verbose:
                    logging.info(f"URL {surl} already processed")
                if not args.nocache:
                    continue
            else:
                r.set(f"cu:{base64.b64encode(surl.encode())}", status['content'])
                r.expire(f"cu:{base64.b64encode(surl.encode())}", cache_expire)
            
            if args.verbose:
                logging.info(f"Downloading and parsing {surl}")

            try:
                article.download()
                article.parse()
            except ArticleException:
                if args.verbose:
                    logging.error(f"Unable to download/parse {surl}")
                continue

            output['data'] = article.html

            nlpFailed = False

            try:
                article.nlp()
            except:
                if args.verbose:
                    logging.error(f"Unable to nlp {surl}")
                nlpFailed = True

                obj = json.dumps(output['data'], indent=4, sort_keys=True)

                if args.verbose:
                    logging.info("Uploading the URL to AIL...\n")
                pyail.feed_json_item(output['data'], output['meta'], ailurlextract, uuid)
                continue
        
            if nlpFailed:
                continue
            
            output['meta']['newspaper:text'] = article.text
            output['meta']['newspaper:authors'] = article.authors
            output['meta']['newspaper:keywords'] = article.keywords
            output['meta']['newspaper:publish_date'] = article.publish_date
            output['meta']['newspaper:top_image'] = article.top_image
            output['meta']['newspaper:movies'] = article.movies

            obj = json.dumps(output['data'], indent=4, sort_keys=True)
            if args.verbose:
                logging.info("Uploading the URL to AIL...\n")
            pyail.feed_json_item(output['data'], output['meta'], ailurlextract, uuid)

logging.info("Done!")
