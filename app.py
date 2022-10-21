import pandas as pd
import os
from dotenv import load_dotenv
import requests
from flask import Flask, render_template, request, send_file
from datetime import datetime
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import pyodbc
import json

app = Flask(__name__)
load_dotenv()  # take environment variables from .env
country_codes = {
    "ukraine": "UKR",
    "slovakia": "SVK",
    "poland": "POL",
    "romania": "ROU"
}


def get_secret_keyvault(secret_name):
    kv_url = os.getenv("KEYVAULT_URL")
    # Authenticate with Azure
    az_credential = DefaultAzureCredential()
    # Retrieve primary key for blob from the Azure Keyvault
    kv_secretClient = SecretClient(vault_url=kv_url, credential=az_credential)
    secret_value = kv_secretClient.get_secret(secret_name).value
    return secret_value


def connect_to_db():
    # Get credentials
    database_secret = get_secret_keyvault("Azure-SQL-Database-secret")
    database_secret = json.loads(database_secret)
    try:
        # Connect to db
        driver = '{ODBC Driver 17 for SQL Server}'
        connection = pyodbc.connect(
            f'DRIVER={driver};'
            f'SERVER=tcp:{database_secret["SQL_DB_SERVER"]};'
            f'PORT=1433;DATABASE={database_secret["SQL_DB"]};'
            f'UID={database_secret["SQL_USER"]};'
            f'PWD={database_secret["SQL_PASSWORD"]}'
        )
        cursor = connection.cursor()
    except pyodbc.Error as error:
        print("Failed to connect to database {}".format(error))
    return connection, cursor


def read_db(sm_code, country_code, start_date, end_date):
    connection, cursor = connect_to_db()
    table_name = os.getenv("AZURE_DB_NAME")
    query = f"""SELECT * \
        FROM {table_name} \
        WHERE sm_code = '{sm_code}' \
        AND country = '{country_code}' \
        AND date \
        BETWEEN '{start_date}' AND '{end_date}' \
        """
    try:
        df_messages = pd.read_sql(query, connection)
    except Exception:
        df_messages = None
        print(f"ERROR: Failed to retrieve SQL table")
    finally:
        cursor.close()
        connection.close()
    return df_messages


@app.route("/menu", methods=['POST'])
def default_page():
    if request.form['password'] == os.getenv("PASSWORD"):
        return render_template('menu.html')
    else:
        return render_template('home.html')


@app.route("/backtomenu", methods=['POST'])
def back_to_default_page():
    return render_template('menu.html')


@app.route("/classify", methods=['POST'])
def classify():
    return render_template('classify.html',
                           countries=json.loads(os.getenv('COUNTRIES')))


@app.route("/wordfreq", methods=['POST'])
def wordfreq():
    return render_template('wordfreq.html', countries=json.loads(os.getenv('COUNTRIES')))


@app.route("/selection", methods=['POST'])
def check_selection():
    payload = {}
    for field in request.form.keys():
        payload[field] = request.form[field]
    if 'labels' not in payload.keys():
        payload['labels'] = []
    else:
        payload['labels'] = payload['labels'].split(',')

    payload['start_date'] = datetime.strptime(payload['start_date'], '%Y-%m-%d')
    payload['end_date'] = datetime.strptime(payload['end_date'], '%Y-%m-%d')
    df = read_db("TL", country_codes[payload['country']], payload['start_date'], payload['end_date'])
    df_date_count = df.groupby('date')['ID'].count()
    return render_template('selection.html',
                           date_count=df_date_count.to_dict(),
                           number_messages=len(df),
                           country=payload['country'],
                           start_date=payload['start_date'].strftime('%Y-%m-%d'),
                           end_date=payload['end_date'].strftime('%Y-%m-%d'),
                           labels=', '.join(payload['labels']),
                           request=request.form['request'],
                           password=os.getenv("PASSWORD"))


@app.route("/sent", methods=['POST'])
def process_request():
    payload = {}
    for field in request.form.keys():
        payload[field] = request.form[field]

    if 'labels' in payload.keys():
        if payload['labels'] != '':
            payload['labels'] = payload['labels'].split(',')
            payload['labels'] = [s.strip() for s in payload['labels']]
            payload['multi_label'] = True
        else:
            payload.pop('labels')

    payload['country_code'] = country_codes[payload['country']]
    payload['config_file'] = payload['country'] + '_' + payload['request'] + '.yaml'
    payload.pop('country')

    url = os.getenv(payload['request'].upper()+"_URL")
    payload.pop('request')

    r = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
    if r.status_code == 200 or r.status_code == 202:
        return render_template('sent.html')
    else:
        return render_template('error.html')


@app.route("/")
def login_page():
    return render_template('home.html')
