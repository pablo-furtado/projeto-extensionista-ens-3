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
    data_inicio = "2026-03-31"
    data_fim = "2026-03-31"
    url = f"https://virtuosa3.clinicaagil.com.br/agenda/jsonAgenda/0/S/1/1/1?start={data_inicio}&end={data_fim}&_=177410552773"
    headers = {

    }

    payload = {
        "start": data_inicio,
        "end": data_fim
    }
    resposta_do_usuario = scraper.get(url=url, data=payload, headers=headers)
    
    informacoes = resposta_do_usuario.json()

    for informacao in informacoes:
        idusuario = informacao.get("id")

        if not idusuario:
            continue

        whatsapp(idusuario)

def whatsapp(idusuario):
    url = f"https://virtuosa3.clinicaagil.com.br/agenda/busca_evento"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }

    
    payload = {
        "id" : idusuario 
    }
    identificacao = scraper.post(url=url, data=payload, headers=headers)
    
    usuario = identificacao.json()
    
    nome_paciente = usuario.get("paciente")
    telefone_cliente = usuario.get("telefone")
    tipo_agendamento = usuario.get("tipo_agendamento")
    if tipo_agendamento == "Ausência":
        return
    
    pprint.pprint(f"{nome_paciente} - {telefone_cliente}")



    
get_login()
