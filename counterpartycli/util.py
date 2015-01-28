#! /usr/bin/python3

import sys
import os
import threading
import decimal
import time
import json
import re
import requests
import collections
import logging
import binascii
from datetime import datetime
from dateutil.tz import tzlocal
import argparse
import configparser
import appdirs
import tarfile
import urllib.request
import shutil

logger = logging.getLogger(__name__)
D = decimal.Decimal

from counterpartylib import server
from counterpartylib.lib import config
from counterpartylib.lib.util import value_input, value_output

rpc_sessions = {}

class RPCError(Exception):
    pass

def rpc(url, method, params=None, ssl_verify=False):
    headers = {'content-type': 'application/json'}
    payload = {
        "method": method,
        "params": params,
        "jsonrpc": "2.0",
        "id": 0,
    }

    if url not in rpc_sessions:
        rpc_session = requests.Session()
        rpc_sessions[url] = rpc_session
    else:
    	rpc_session = rpc_sessions[url]

    response = None
    TRIES = 12
    for i in range(TRIES):
        try:
            response = rpc_session.post(url, data=json.dumps(payload), headers=headers, verify=ssl_verify)
            if i > 0:
                logger.debug('Successfully connected.')
            break
        except requests.exceptions.SSLError as e:
            raise e
        except requests.exceptions.ConnectionError:
            logger.debug('Could not connect to {}. (Try {}/{})'.format(url, i+1, TRIES))
            time.sleep(5)

    if response == None:
        raise RPCError('Cannot communicate with {}.'.format(url))
    elif response.status_code not in (200, 500):
        raise RPCError(str(response.status_code) + ' ' + response.reason + ' ' + response.text)

    # Return result, with error handling.
    response_json = response.json()
    if 'error' not in response_json.keys() or response_json['error'] == None:
        return response_json['result']
    else:
        raise RPCError('{}'.format(response_json['error']))

def api(method, params=None):
    return rpc(config.COUNTERPARTY_RPC, method, params=params, ssl_verify=config.COUNTERPARTY_RPC_SSL_VERIFY)

def is_divisible(asset):
    if asset in (config.BTC, config.XCP, 'leverage', 'value', 'fraction', 'price', 'odds'):
        return True
    else:
        sql = '''SELECT * FROM issuances WHERE (status = ? AND asset = ?)'''
        bindings = ['valid', asset]
        issuances = api('sql', {'query': sql, 'bindings': bindings})

        if not issuances: raise AssetError('No such asset: {}'.format(asset))
        return issuances[0]['divisible']

def value_in(quantity, asset):
    return value_input(quantity, asset, is_divisible(asset))

def value_out(quantity, asset):
    return value_output(quantity, asset, is_divisible(asset))

def add_config_arguments(arg_parser, config_args, default_config_file):
    # Confg file
    cmd_args = arg_parser.parse_known_args()[0]
    #print(cmd_args)
    if not cmd_args.config_file:
        config_dir = appdirs.user_config_dir(appauthor=config.XCP_NAME, appname=config.APP_NAME, roaming=True)
        if not os.path.isdir(config_dir):
            os.makedirs(config_dir)
        cmd_args.config_file = os.path.join(config_dir, default_config_file)

    logger.info('Loading configuration file: `{}`'.format(cmd_args.config_file))
    configfile = configparser.ConfigParser()
    configfile.read(cmd_args.config_file)

    if not 'Default' in configfile:
        configfile['Default'] = {}

    # Initialize default values with the config file.
    for arg in config_args:
        key = arg[0][-1].replace('--', '')
        if 'action' in arg[1] and arg[1]['action'] == 'store_true' and key in configfile['Default'] and configfile['Default'].getboolean(key):
            arg[1]['default'] = True
        elif key in configfile['Default'] and configfile['Default'][key]:
            arg[1]['default'] = configfile['Default'][key]
        arg_parser.add_argument(*arg[0], **arg[1])

    return arg_parser

# Download bootstrap database
def bootstrap(check_if_exists=False, ask_confirmation=False):
    bootstrap_url = 'https://s3.amazonaws.com/counterparty-bootstrap/counterpartyd-db.latest.tar.gz'
    bootstrap_url_testnet = 'https://s3.amazonaws.com/counterparty-bootstrap/counterpartyd-testnet-db.latest.tar.gz'

    data_dir = appdirs.user_data_dir(appauthor=config.XCP_NAME, appname=config.APP_NAME, roaming=True)
    database = os.path.join(data_dir, '{}.{}.db'.format(config.APP_NAME, config.VERSION_MAJOR))
    database_testnet = os.path.join(data_dir, '{}.{}.testnet.db'.format(config.APP_NAME, config.VERSION_MAJOR))

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    if check_if_exists and os.path.exists(database):
        return

    if ask_confirmation:
        question = 'Do you want to download bootstrap database from https://s3.amazonaws.com/counterparty-bootstrap/ ? (y/N): '
        if input(question).lower() != 'y':
            return

    print("downloading mainnet database from {}.".format(bootstrap_url))
    urllib.request.urlretrieve(bootstrap_url, 'counterpartyd-db.latest.tar.gz')
    print("extracting.")
    with tarfile.open('counterpartyd-db.latest.tar.gz', 'r:gz') as tar_file:
        tar_file.extractall()
    print('Copy {} to {}'.format('counterpartyd.9.db', database))
    shutil.copy('counterpartyd.9.db', database)
    os.remove('counterpartyd-db.latest.tar.gz')

    print("downloading testnet database from {}.".format(bootstrap_url_testnet))
    urllib.request.urlretrieve(bootstrap_url_testnet, 'counterpartyd-testnet-db.latest.tar.gz')
    print("extracting.")
    with tarfile.open('counterpartyd-testnet-db.latest.tar.gz', 'r:gz') as tar_file:
        tar_file.extractall()
    print('Copy {} to {}'.format('counterpartyd.9.testnet.db', database_testnet))
    shutil.copy('counterpartyd.9.testnet.db', database_testnet)
    os.remove('counterpartyd-testnet-db.latest.tar.gz')


# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
