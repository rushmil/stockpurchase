import os
import random
import sqlite3
from datetime import datetime, timedelta

import yfinance as yf

from prophet import Prophet
import math
import pandas as pd
import requests

from flask import Flask, render_template, request, redirect, session, json, jsonify
import json

app = Flask(__name__)
api_key = '25092a0182ac40779540b1bf208c57e9'
loggedin = False

app.secret_key = 'your-secret-key'

YERST = (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
TODAY = (datetime.today()).strftime('%Y-%m-%d')
TMRW = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')


@app.route('/')
def home():
    return redirect('/register')


@app.route('/visual', methods=["POST", "GET"])
def visual():
    global symbol
    global period
    if request.method == 'POST':
        # Retrieve the symbol from the form
        symbol = request.form.get('symbol')
        shares = int(request.form.get('shares'))
        period = int(request.form.get("period"))

        url = f'https://api.twelvedata.com/price?symbol={
            symbol}&apikey={api_key}'

        response = requests.get(url)
        data = response.json()
        print(url)

        # company = yf.Ticker(symbol).info['shortName']
        # Debugging statement to check the symbol
        print(f"Received symbol: {symbol}")

        if not symbol:
            return "Error: No symbol provided", 400

            # Download the stock data

        cdata = float(data['price'])
        sprice = cdata * shares

        pipe_response = requests.post(
            "http://127.0.0.1:5000/pipe", json={"symbol": symbol, "period": period})
        if pipe_response.status_code != 200:
            return "Error: Could not retrieve forecast data", 500

        forecast_data = pipe_response.json()
        forecast_list = json.loads(forecast_data["fore"])

        # Get the "Close" value of the last row
        pdata = forecast_list[-1]['yhat']
        tpdata = pdata * shares

        return render_template("visual.html", loggedin='user_id' in session, Price=cdata, shares=shares, SPrice=sprice, period=period, pdata=pdata, tpdata=tpdata)

    return render_template("visual.html", loggedin='user_id' in session)


@app.route('/transact', methods=["POST", "GET"])
def transact():
    if request.method == "POST":

        bsymbol = request.form.get("bsymbol")
        shares = int(request.form.get("shares"))
        # company = yf.Ticker(bsymbol).info['shortName']
        type = request.form.get("type")

        # df = yf.download(bsymbol, TODAY, TMRW)
        url = f'https://api.twelvedata.com/price?symbol={
            bsymbol}&apikey={api_key}'

        response = requests.get(url)
        data = response.json()

        url1 = f'https://api.twelvedata.com/quote?symbol={
            bsymbol}&apikey={api_key}'
        response1 = requests.get(url1)
        data1 = response1.json()
        company = data1['name']

        if len(data) == 0:
            return render_template('buy.html', loggedin='user_id' in session, error="Stock does not exist")
        # df.reset_index(inplace=True)
        cdata = math.ceil(float(data['price'])*100)/100
        print(cdata)
        with sqlite3.connect('database.db') as con:
            curr = con.cursor()
            curr.execute("SELECT cash FROM users WHERE id=?",
                         (session['user_id'],))
            result = curr.fetchone()
            currentcash = int(result[0])

            amount = cdata*shares

            if type == 'buy':
                if currentcash >= amount:
                    changedCash = currentcash - amount
                    curr.execute("UPDATE users SET cash=? WHERE id=?",
                                 (changedCash, session['user_id']))
                    curr.execute(
                        "SELECT shares, total FROM assets WHERE symbol=? AND user_id=?", (bsymbol, session['user_id'],))
                    result = curr.fetchone()
                    if result:
                        cshare = result[0]
                        total = result[1]
                        curr.execute('UPDATE assets SET shares=?, total=? WHERE symbol=? AND user_id=?',
                                     (cshare+shares, total*(cshare+shares), bsymbol, session['user_id']))
                    else:
                        curr.execute('INSERT INTO assets (user_id, name, price, shares, total, symbol) VALUES(?, ?, ?, ?, ?, ?)',
                                     (session['user_id'], company, cdata, shares, cdata * shares, bsymbol,))
                    return render_template('buy.html', loggedin='user_id' in session, cmp=company, share=shares, money=cdata*shares, color="green", type='bought')
                else:
                    return render_template('buy.html', loggedin='user_id' in session, error="Not enough money", color="red")
            elif type == 'sell':
                curr.execute(
                    "SELECT shares, total FROM assets WHERE symbol=? AND user_id=?", (bsymbol, session['user_id'],))
                result = curr.fetchone()
                cshare = result[0]
                total = result[1]
                if shares <= cshare:
                    changedCash = currentcash + amount
                    curr.execute("UPDATE users SET cash=? WHERE id=?",
                                 (changedCash, session['user_id']))
                    curr.execute('UPDATE assets SET shares=?, total=? WHERE symbol=? AND user_id=?',
                                 (cshare-shares, total*(cshare-shares), bsymbol, session['user_id']))
                    return render_template('buy.html', loggedin='user_id' in session, cmp=company, share=shares, money=cdata*shares, color="green", type='sold')
                else:
                    return render_template('buy.html', loggedin='user_id' in session, error="You do not own enough shares", color="red")

    return render_template('buy.html', loggedin='user_id' in session)


@app.route('/pipe', methods=["GET", "POST"])
def pipe():

    START = "2015-01-01"

    df = yf.download(symbol, "2024-01-29", "2024-06-18")
    df.reset_index(inplace=True)

    df_train = df[['Date', 'Close']]
    df_train = df_train.rename(columns={"Date": "ds", "Close": "y"})

    m = Prophet()
    m.fit(df_train)
    future = m.make_future_dataframe(periods=int(period) * 365)
    forecast = m.predict(future)
    fore_json = forecast.to_json(orient='records')

    df['Date'] = (df['Date'].astype('int64') // 10**6).astype('int64')
    json_data = df.to_json(orient='records')

    return jsonify({"fore": fore_json, "res": json_data, "name": symbol})


@app.route('/deposit', methods=["POST", "GET"])
def deposit():
    if request.method == "POST":
        amount = int(request.form.get("money"))
        print(amount)
        with sqlite3.connect('database.db') as con:
            curr = con.cursor()
            curr.execute("SELECT cash FROM users WHERE id=?",
                         (session['user_id'],))
            result = curr.fetchone()
            currentcash = result[0]

            changedCash = currentcash + amount
            curr.execute("UPDATE users SET cash=? WHERE id=?",
                         (changedCash, session['user_id']))
            curr.close()
    return render_template('deposit.html', loggedin='user_id' in session)


@app.route('/dashboard')
def dashboard():
    if 'user_id' in session:
        with sqlite3.connect('database.db') as con:
            curr = con.cursor()
            curr.execute(
                "SELECT username, cash FROM users WHERE id=?", (session['user_id'],))
            result = curr.fetchone()
            curr.close()
        return render_template('dashboard.html', loggedin='user_id' in session, username=result[0], cash=result[1])
    return render_template('dashboard.html', loggedin='user_id' in session)


@app.route('/login', methods=["POST", "GET"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        with sqlite3.connect('database.db') as con:
            curr = con.cursor()
            curr.execute("SELECT * FROM users WHERE username =?", (username,))
            result = curr.fetchone()
            curr.close()
            if result and password == result[2]:
                session['user_id'] = result[0]
                return redirect('/deposit')
            else:
                return render_template('login.html', error="Incorrect username or password")
    return render_template('login.html')


@app.route('/register', methods=["POST", "GET"])
def register():
    if request.method == "POST":
        with sqlite3.connect('database.db') as con:
            username = request.form.get("username")
            password = request.form.get("password")
            conpassword = request.form.get("conpassword")
            if password != conpassword:
                return render_template("register.html", error="Passwords do not match!")
            curr = con.cursor()
            curr.execute(
                "SELECT username FROM users WHERE username=?", (username,))
            result = curr.fetchone()
            if result != None:
                return render_template('register.html', error="Username already exists!")
            else:
                curr.execute(
                    "INSERT INTO users (username, password, cash) VALUES (?,?, ?)", (username, password, 0))
                con.commit()
                return render_template('login.html')
    return render_template('register.html')


@app.route('/portfolio', methods=["POST", "GET"])
def portfolio():
    symbols = []
    y = []
    assets = 0
    inv = 0
    with sqlite3.connect('database.db') as con:
        curr = con.cursor()
        curr.execute("SELECT * FROM assets WHERE user_id=?",
                     (session['user_id'],))
        result = curr.fetchall()
        for row in result:
            stsymbol = row[6]
            url = f'https://api.twelvedata.com/price?symbol={
                stsymbol}&apikey={api_key}'
            response = requests.get(url)
            data = response.json()
            cdata = math.ceil(float(data['price'])*100)/100

            value = cdata * row[4]
            if row[4] != 0:
                symbols.append(stsymbol)
                y.append(value)
                assets = assets+value
                inv = inv + row[5]
        for i in range(0, len(result)):
            result[i] = result[i] + (y[i],)

    colors = generate_similar_colors("#2392dc", len(y)+1, 50)
    print(result)

    return render_template("portfolio.html", loggedin="user_id" in session, name=symbols, y=y, colors=colors, result=result, assets=assets, inv=inv)


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb_color):
    """Convert RGB tuple to hex color."""
    return '#{:02x}{:02x}{:02x}'.format(rgb_color[0], rgb_color[1], rgb_color[2])


def generate_similar_colors(base_hex, num_colors, variation):
    """
    Generate a list of similar colors in hex.

    Parameters:
        base_hex (str): The base color in hex format.
        num_colors (int): Number of similar colors to generate.
        variation (int): Amount of variation for the RGB values.

    Returns:
        List of hex colors.
    """
    base_rgb = hex_to_rgb(base_hex)
    similar_colors = []

    for _ in range(num_colors):
        new_rgb = tuple(
            max(0, min(255, base_rgb[i] +
                random.randint(-variation, variation)))
            for i in range(3)
        )
        similar_colors.append(rgb_to_hex(new_rgb))

    return similar_colors


@app.route('/logout')
def logout():
    session.clear()
    return redirect("/")
