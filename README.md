# ail-feeder-activity-pub

External ActivityPub feeder for AIL-framework.

## How to use

### Get instances

Get an API token on https://instances.social/api/token and enter it in the `instanceFetcher.py` file. 

Running this program will create a file called `instances.txt` with all the available Mastodon instances that you can join.

The documentation of the API and how to use can be found here: https://instances.social/api/doc/

NB: The file can be modified with the parameters you want in the request.

### Create accounts

To scan the instances, you need to create an account. With all the instances, that have been found, automated account creation is supported. The file `accountCreator.py` will try to create an account for every instance in `instances.txt` with a randomised email address and a password you can choose. Once all the accounts have been created, the program also verifies the email addresses of the accounts and saves the instances, which are ready to be crawled, in `readyInstances.txt`.

Use the program with the following command:
```
ail-feeder-activity-pub: python3 bin/accountCreator.py -h
usage: accountCreator.py [-h] [--verbose] password

positional arguments:
  password    the password you want to use

optional arguments:
  -h, --help  show this help message and exit
  --verbose   verbose output
```

NB: For some instances, it is not possible to create an account or the account creation is skipped. For example some instances are private and you cannot register a new account without being invited. Some instances also require manual approval, those instances are skipped.

### Crawl the ready instances

After having created accounts for the instances, the `feeder.py` program, will scan those instances and extract all the metadata and other data it can and the upload it to the AIL framework.

The program can be used with the following command:
```
ail-feeder-activity-pub: python3 bin/feeder.py -h        
usage: feeder.py [-h] [--verbose] [--nocache] query

positional arguments:
  query       query to search on ActivityPub to feed AIL

optional arguments:
  -h, --help  show this help message and exit
  --verbose   verbose output
  --nocache   disable cache
```

NB: Make sure to enter the required fields in the `ail-feeder-activitypub.cfg` file. Also make sure there is an instance of the AIL-framework running. There is a sample of the cfg file you can use.

## Notes

If you want to scan a separate instance where you already have an account, simply add the URL of the registration page of the instance in an empty `readyInstances.txt` file and the login credentials in `credentials.txt`. Then run the `feeder.py` program.