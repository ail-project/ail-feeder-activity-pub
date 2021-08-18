import argparse
import logging
import re
import time

import requests
from pydispo import *
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s:%(message)s', level=logging.INFO, datefmt='%I:%M:%S')

# Parse the arguments
parser = argparse.ArgumentParser()
parser.add_argument("password", help="the password you want to use")
parser.add_argument("--verbose", help="verbose output", action="store_true")
args = parser.parse_args()

# Generate a random email address
email = generate_email_address(size=10, storeInFile='credentials.txt', mode='w')
with open('credentials.txt', 'a') as f:
    f.write(f'\n{args.password}')
username = email.split('@')[0]

options = Options()
options.headless = True

with open("instances.txt", 'r') as f:
    instances = f.readlines()
if args.verbose:
    logging.info("Starting account creation...\n")
browser = webdriver.Firefox(options=options)
browser.set_page_load_timeout(10)

# Looping through the instances in 'instances.txt'
for instance in instances:
    if args.verbose:
        logging.info(instance.replace('\n', ''))
    unreachable = False

    # Request the page
    try:
        browser.get(f'https://{instance}')
    # If the page is not loaded within 10 seconds, skip it
    except TimeoutException:
        unreachable = True
        if args.verbose:
            logging.error("Unreachable!\n")
        continue
    if unreachable:
        continue

    # Check if the page has the default layout for registration, if it does, fill in the form and submit it
    # Otherwise skip it
    try:
        WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.NAME, 'user[account_attributes][username]')))
        browser.find_element_by_name('user[account_attributes][username]').send_keys(username)
        WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.NAME, 'user[email]')))
        emailField = browser.find_element_by_name('user[email]')
        emailField.send_keys(email)
        WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.NAME, 'user[password]')))
        browser.find_element_by_name('user[password]').send_keys(args.password)
        emailField.clear()
        emailField.send_keys(email)
        WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.NAME, 'user[password_confirmation]')))
        browser.find_element_by_name('user[password_confirmation]').send_keys(args.password)
        approval = False

        # Check if the registration is based on a request. If it is, skip it
        try:
            browser.find_element_by_name('user[invite_request_attributes][text]')
            approval = True
        except NoSuchElementException:
            continue
        finally:
            # Submit the form
            try:
                WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.ID, 'registration_user_agreement')))
                browser.find_element_by_id('registration_user_agreement').click()
            except TimeoutException:
                WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.ID, 'user_agreement')))
                browser.find_element_by_id('user_agreement').click()
                continue
            finally:
                if approval:
                    if args.verbose:
                        logging.error("Approval required, skipping...\n")
                    continue
                time.sleep(2)
                buttons = browser.find_elements_by_name('button')
                if len(buttons) != 0:
                    buttons[0].click()
                else:
                    logging.error("No button found, skipping...")
                    continue
                time.sleep(5)
                if args.verbose:
                    logging.info("Registered successfully!\n")
                continue

    except:
        if args.verbose:
            logging.error("This instance is either private, doesn't accept new registrations, has a custom login page or none at all, or something else went wrong.\n")
        continue

if args.verbose:
    logging.info("Account creation done!\n")
time.sleep(5)

# Fetch the emails from the server
login_id = email[:email.find('@')]
login_domain = email[email.find('@')+1:]
http_get_url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login_id}&domain={login_domain}"
response = requests.get(http_get_url)
if not response.status_code == 200:
    logging.error("Invalid server response code ", response.status_code)
response = response.json()

if args.verbose:
    logging.info("Starting email verification...\n")

with open('readyInstances.txt', 'w') as f:
    # Loop through the emails and verify the address to finish the account creation
    for nm in range(len(response)):
        failed = False
        # Get the emails
        http_get_url_single = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login_id}&domain={login_domain}&id={str(response[nm]['id'])}"
        response2 = requests.get(http_get_url_single)
        response2 = response2.json()
        try:
            # Search for the email verification code
            links = re.findall('https://.*/auth/.*', response2['textBody'])
            if len(links) != 0:
                confirmationLink = links[0]
            else:
                logging.error("No link found, skipping...")
                continue
            if args.verbose:
                logging.info(confirmationLink)
            # Open the email verification link to verify the email
            try:
                browser.get(confirmationLink)
            except TimeoutException:
                failed = True
                continue
            if failed:
                continue
            time.sleep(2)

            # Extract the link and add it to the instances which are ready to be used
            url = confirmationLink.split('/auth')[0].replace('https://', '')
            if args.verbose:
                logging.info(f'{url}\n')
            f.write(f'{url}\n')
        except:
            continue

browser.close()
if args.verbose:
    logging.info("Email verification done!\n")
