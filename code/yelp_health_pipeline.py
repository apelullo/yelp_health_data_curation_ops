#!/usr/bin/env python
# coding: utf-8

# # Yelp-AWS Processing Pipeline
# * Get zip file from Yelp bucket if not in CDH bucket and unzip to json stream - each object is a facility
# * Process json - extract facility, category, and review datasets
# * Upload zip, json, and csv's to respective cdh buckets and remove from directories

# In[1]:


# Modules
import pandas as pd
import math
import numpy as np
import scipy as sp

import io
import os
import sys
import pytz
from datetime import datetime
from time import gmtime, strftime

import glob
import zipfile
import gzip
import shutil
import re
import json
from json import JSONDecoder, JSONDecodeError
from pandas.io.json import json_normalize
from collections import defaultdict

import boto3
from botocore.exceptions import NoCredentialsError
from boto.s3.connection import S3Connection
from boto.glacier.layer1 import Layer1
from boto.glacier.concurrent import ConcurrentUploader

# Pandas view options
pd.set_option('display.max_columns', 100)
pd.set_option('display.max_rows', 200)
pd.set_option('precision', 4)


# ## Program Parameters

# In[2]:


# Program constants
BASE_PATH = '/home/ec2-user/yelp/data/'
ZIP_PATH = BASE_PATH + 'zip_files/'
JSON_PATH = BASE_PATH + 'json_files/'
MASTER_PATH = BASE_PATH + 'master_files/'
SUMMARY_PATH = BASE_PATH + 'summary_files/'
LOG_PATH = BASE_PATH + 'logs/'

ZIP_ARCHIVE_NAME = 'yelp_zip_archive_ids.csv'
JSON_ARCHIVE_NAME = 'yelp_json_archive_ids.csv'
MASTER_ARCHIVE_NAME = 'yelp_master_archive_ids.csv'


# In[3]:


# CDH access parameters
CDH_ACCESS_KEY_ID = "REDACTED"
CDH_SECRET_ACCESS_KEY = "REDACTED"
CDH_REGION = "us-east-2"

# Yelp access parameters
YELP_ACCESS_KEY_ID = 'REDACTED'
YELP_SECRET_ACCESS_KEY = 'REDACTED'


# In[4]:


# Bucket names
YELP_BUCKET = 'yelp-syndication'
CDH_BUCKET_ZIP_GLACIER = 'yelp-zip-files-glacier'
CDH_BUCKET_JSON_GLACIER = 'yelp-json-files-glacier'
CDH_BUCKET_MASTER_GLACIER = 'yelp-master-files-glacier'
CDH_BUCKET_MASTER = 'yelp-master-files'
CDH_BUCKET_AUX = 'yelp-auxiliary-files'


# In[5]:


# Connect to s3
s3_yelp = boto3.client('s3', aws_access_key_id=YELP_ACCESS_KEY_ID, aws_secret_access_key=YELP_SECRET_ACCESS_KEY)
s3_cdh = boto3.client('s3', aws_access_key_id=CDH_ACCESS_KEY_ID, aws_secret_access_key=CDH_SECRET_ACCESS_KEY, region_name=CDH_REGION)


# ## Functions

# ### Step 1: Get new zip file from Yelp bucket and unzip

# In[6]:


def get_new_file(file, zip_file_path, json_file_path):
    
    # Upload files to zip path
    if os.path.exists(ZIP_PATH):
        try:
            print('Now downloading:', zip_file_path)
            s3_yelp.download_file(Bucket=YELP_BUCKET, Key=file, Filename=zip_file_path)
        except:
            print('There was a problem uploading the file:',zip_file_path)
            return False
    else:
        print('Zip path does not exist!' 'Please Create the appropriate directories.')
        return False

    # Unzip files to json path
    if os.path.exists(JSON_PATH):
        try:
            print('Now unziping:', json_file_path)
            with gzip.open(zip_file_path, 'rb') as f_in:
                with open(json_file_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except:
            print('There was a problem unziping the file:', json_file_path)
            return False
    else:
        print('JSON path does not exist!' 'Please Create the appropriate directories.')
        return False
    
    return True


# ### Step 2: Process JSON file

# In[7]:


NOT_WHITESPACE = re.compile(r'[^\s]')

def decode_stacked(document, pos=0, decoder=JSONDecoder()):
    while True:
        match = NOT_WHITESPACE.search(document, pos)
        if not match:
            return
        pos = match.start()

        try:
            obj, pos = decoder.raw_decode(document, pos)
        except JSONDecodeError:
            # do something sensible if there's some error
            raise
        yield obj


# In[8]:


def extract_data():
    for file in glob.glob(JSON_PATH + '*.json'):
        file_name = file.split('/')[-1].split('_')[0]
        if os.path.exists(MASTER_PATH) and (MASTER_PATH+file_name+'_facilities.csv') not in glob.glob(MASTER_PATH+'*.csv'):
            try:
                print('Now reading:', file)
                with open(file,'r') as f:
                    data = f.read()
                print('Now processing:', file)

                fac_data = []
                cat_data = []
                rev_data = []
                summary_data = []
                count = 0

                for fac in decode_stacked(data):

                    # Facility data
                    fac_id = fac['id']
                    fac_name = fac['name']
                    fac_is_closed = fac['is_closed']
                    review_count = fac['review_count']
                    fac_rating = fac['rating']
                    fac_updated_time = fac['time_updated']
                    phone = fac['phone']
                    business_url = fac['business_url']
                    fac_url = fac['url']

                    # Facility data: location
                    address = ' '.join([item for item in fac['location']['address'] if item is not None]).strip()
                    city = fac['location']['city']
                    state = fac['location']['state']
                    country = fac['location']['country']
                    postal_code = fac['location']['postal_code']
                    latitude = fac['location']['coordinate']['latitude']
                    longitude = fac['location']['coordinate']['longitude']

                    fac_temp = [fac_id, fac_name, fac_is_closed, review_count, fac_rating, fac_updated_time, phone, business_url, 
                                fac_url, address, city, state, country, postal_code, latitude, longitude]
                    fac_data.append(fac_temp)


                    # Categories
                    for item in fac['categories']:
                        cat_temp = [fac_id, item['alias'], item['title']]
                        cat_data.append(cat_temp) 


                    # Reviews
                    for item in fac['reviews']:
                        rev_id = item['id']
                        rev_rating = item['rating']
                        review = item['text']
                        user = item['user']['name']
                        rev_created_time = item['created']
                        rev_url = item['url']
                        rev_is_selected = item['is_selected']

                        rev_temp = [fac_id, rev_id, rev_rating, review, 
                                    user, rev_created_time, rev_url, rev_is_selected]
                        rev_data.append(rev_temp) 

                    if count % 100000 == 0:
                        print(count, 'facilities processed...')
                    count += 1

                # Writing csv files...
                del data
                print('Writing csv files...')

                # Write data to csv
                fac_cols = ['fac_id','fac_name','fac_is_closed','review_count','fac_rating','fac_updated_time','phone',
                            'business_url','fac_url','address','city','state','country','postal_code','latitude','longitude']
                fac_data = pd.DataFrame(data=fac_data, columns=fac_cols)
                fac_data.to_csv(MASTER_PATH + file_name + '_facilities.csv')
                print('Facility data created!')

                cat_cols = ['fac_id','alias','title']
                cat_data = pd.DataFrame(data=cat_data, columns=cat_cols)
                cat_data.to_csv(MASTER_PATH + file_name + '_categories.csv')
                print('Category data created!')

                rev_cols = ['fac_id', 'rev_id', 'rev_rating', 'review', 
                            'user', 'rev_created_time', 'rev_url', 'rev_is_selected']
                rev_data = pd.DataFrame(data=rev_data, columns=rev_cols)
                rev_data.to_csv(MASTER_PATH + file_name + '_reviews.csv')
                print('Review data created!')
                
                # Extract summary data
                print('Extracting summary data...')
                daily_data = s3_cdh.get_object(Bucket=CDH_BUCKET_AUX, Key='daily_data.csv')
                daily_data = pd.read_csv(io.BytesIO(daily_data['Body'].read()), index_col=0)
                summary_data.append([file_name, len(cat_data.alias.unique()),
                                     len(fac_data), fac_data['fac_rating'].mean(), fac_data['fac_rating'].median(),
                                     fac_data['review_count'].mean(), fac_data['review_count'].median(),
                                     len(rev_data), rev_data['rev_rating'].mean(), rev_data['rev_rating'].median()])
                summary_cols = ['date','cat_count',
                                'fac_count','fac_rating_mean','fac_rating_med',
                                'fac_rev_count_mean','fac_rev_count_med',
                                'rev_count','rev_rating_mean','rev_rating_med']
                summary_data = pd.DataFrame(summary_data, columns=summary_cols)
                summary_data = summary_data[~summary_data['date'].isin(daily_data['date'])]
                daily_data = pd.concat([daily_data,summary_data])
                daily_data.to_csv(SUMMARY_PATH + 'daily_data.csv')
                daily_data.to_csv(SUMMARY_PATH + file_name + '_daily_data.csv')
                print('Summary data created!')
                
                # Delete temporary data
                print('Removing temporary files...')
                del fac_data
                del cat_data
                del rev_data
                del daily_data
                del summary_data
                
            except:
                print('Data extraction failed! Please retry.')
                return False
        
    return True


# ### Step 3: Upload files to s3 and remove from directories

# In[9]:


def upload_to_aws(local_file, bucket, s3_file, args_dict, overwrite=False):
    if 'Contents' in s3_cdh.list_objects(Bucket=bucket).keys() and not overwrite:
        uploaded = [item['Key'] for item in s3_cdh.list_objects(Bucket=bucket)['Contents']]
    else:
        uploaded = []
    
    if s3_file not in uploaded:
        try:
            print('Now uploading: ', s3_file)
            s3_cdh.upload_file(Filename=local_file, Bucket=bucket, Key=s3_file, ExtraArgs=args_dict)
            print("Upload Successful")
            return True
        except FileNotFoundError:
            print("The file was not found")
            return False
        except NoCredentialsError:
            print("Credentials not available")
            return False


# In[10]:


def save_files():
    try:
        # Zip files: glacier
        for file in glob.glob(ZIP_PATH + '*.gz'):
            local_file_name = file
            aws_file_name = file.split(ZIP_PATH)[-1]
            bucket_name = CDH_BUCKET_ZIP_GLACIER

            args_dict=dict()
            args_dict['StorageClass']='DEEP_ARCHIVE'

            uploaded = upload_to_aws(local_file_name, bucket_name, aws_file_name, args_dict)
            if uploaded:
                os.remove(file)
            else:
                print('File ', file, ' not uploaded!')

        # JSON files: glacier
        for file in glob.glob(JSON_PATH + '*.json'):
            local_file_name = file
            aws_file_name = file.split(JSON_PATH)[-1]
            bucket_name = CDH_BUCKET_JSON_GLACIER

            args_dict=dict()
            args_dict['StorageClass']='DEEP_ARCHIVE'

            uploaded = upload_to_aws(local_file_name, bucket_name, aws_file_name, args_dict)
            if uploaded:
                os.remove(file)
            else:
                print('File ', file, ' not uploaded!')

        # Master files: glacier
        for file in glob.glob(MASTER_PATH + '*.csv'):
            local_file_name = file
            aws_file_name = file.split(MASTER_PATH)[-1]
            bucket_name = CDH_BUCKET_MASTER_GLACIER

            args_dict=dict()
            args_dict['StorageClass']='DEEP_ARCHIVE'

            uploaded = upload_to_aws(local_file_name, bucket_name, aws_file_name, args_dict)
            if uploaded:
                print('Glacier upload complete...')
            else:
                print('File ', file, ' not uploaded!')

        # Master files: standard infrequent access
        for file in glob.glob(MASTER_PATH + '*.csv'):
            local_file_name = file
            aws_file_name = file.split(MASTER_PATH)[-1]
            bucket_name = CDH_BUCKET_MASTER

            args_dict=dict()
            args_dict['StorageClass']='STANDARD_IA'

            uploaded = upload_to_aws(local_file_name, bucket_name, aws_file_name, args_dict)
            if uploaded:
                os.remove(file)
            else:
                print('File ', file, ' not uploaded!')
                
        # Summary files: standard
        for file in glob.glob(SUMMARY_PATH + '*.csv'):
            local_file_name = file
            aws_file_name = file.split(SUMMARY_PATH)[-1]
            bucket_name = CDH_BUCKET_AUX

            args_dict=dict()
            args_dict['StorageClass']='STANDARD'

            uploaded = upload_to_aws(local_file_name, bucket_name, aws_file_name, args_dict, overwrite=True)
            if uploaded:
                os.remove(file)
            else:
                print('File ', file, ' not uploaded!')
    
    except:
        print('File save incomplete! Please retry.')
        return False
    
    return True


# ### Step 4: Bringing it all together

# In[11]:


def process_files():
    # Get file lists
    yelp_zip_files = [[item['Key'], item['Key'].split('/')[-1]] for item in s3_yelp.list_objects_v2(Bucket=YELP_BUCKET, Prefix='upenn/')['Contents']]
    cdh_zip_files = [item['Key'] for item in s3_cdh.list_objects_v2(Bucket=CDH_BUCKET_ZIP_GLACIER)['Contents']]
    
    # Process files
    for item in yelp_zip_files:
        file=item[0]
        name=item[1]
        zip_file_path = ZIP_PATH+name
        json_file_path = (JSON_PATH+name).split('.gz')[0]
        
        # Check if file has already been processed and archived - upload function MUST verify this
        if name not in cdh_zip_files:
            # Extract zip and json files
            if not get_new_file(file, zip_file_path, json_file_path):
                print('There was a problem extracting the zip and json files! Now exiting.')
                return False
            # Process json file
            if not extract_data():
                print('There was a problem extracting the data! Now exiting.')
                return False
            # Upload files to s3
            if not save_files():
                print('There was a problem saving the files! Now exiting.')
                return False
            
    return True


# ## Main Program
# * Add functionality here to shut down EC2 instance when complete and send email notification / add log record

# In[12]:


if process_files():
    print('All files processed correctly! Our work here is done - See you next time!')
else:
    print('The program encountered an error! Please check the processing status and restart! =(')


# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:




