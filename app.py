from dotenv import load_dotenv
load_dotenv()

import os
import cloudscraper
import pprint
scraper = cloudscraper.create_scraper()

def get_login():
    

    url = "https://virtuosa3.clinicaagil.com.br/auth/login"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "identity": os.getenv("EMAIL_LOGIN"),
        "password": os.getenv("PASSWORD")
    }

    resposta_do_login = scraper.post(url=url, data=payload, headers=headers)
    cliente()

def cliente(): 
    url = "https://virtuosa3.clinicaagil.com.br/agenda/jsonAgenda/0/S/1/1/1?start=2026-03-21&end=2026-03-22&_=177410552773"
    headers = {

    }

    payload = {
        "start": "2026-03-21",
        "end": "2026-03-21"
    }
    resposta_do_usuario = scraper.post(url=url, data=payload, headers=headers)

    pprint.pprint(resposta_do_usuario.json())

get_login()