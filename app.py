from dotenv import load_dotenv
load_dotenv()


import locale
locale.setlocale(locale.LC_TIME, "pt_BR.UTF-8")


import os
import cloudscraper
import pprint
from datetime import datetime

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

    ################## PEGAR OS CLIENTES DO DIA ##################
    resposta_do_usuario = scraper.get(url=url, data=payload, headers=headers)
    
    informacoes = resposta_do_usuario.json()

    for informacao in informacoes:
        idusuario = informacao.get("id")

        if not idusuario:
            continue

        mensagem_editada, numero_telefone, nome_paciente = whatsapp(idusuario)
        if not mensagem_editada:
            continue
        
        print(f"Mensagem editada: {mensagem_editada}\n\n", f"Telefone: {numero_telefone}\n", f"Nome do paciente: {nome_paciente}\n\n")













def whatsapp(idusuario):
    url = f"https://virtuosa3.clinicaagil.com.br/agenda/busca_evento"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }

    
    payload = {
        "id" : idusuario 
    }

    ############### INFORMAÇÕES DOS CLIENTES ##################
    identificacao = scraper.post(url=url, data=payload, headers=headers)
    
    usuario = identificacao.json()


    nome_paciente = usuario.get("paciente")
    telefone_cliente = usuario.get("telefone")
    tipo_agendamento = usuario.get("tipo_agendamento")
    status = usuario.get("status")
    mensagem = usuario.get("mensagem_whatsapp")
    data_do_agendamento = usuario.get("data_inicio")
    hora_inicial = usuario.get("hora_inicio")
    hora_inicial = datetime.strptime(hora_inicial, "%H:%M:%S").strftime("%H:%M")

    data_agendamento_formatada = datetime.strptime(data_do_agendamento, "%Y-%m-%d")
    dia_da_semana = data_agendamento_formatada.strftime("%A")
    
    
    data_agendamento_formato_br = data_agendamento_formatada.strftime("%d/%m/%Y")

    if tipo_agendamento == "Ausência" or status == "FJ":
        return None, None, None
    

    mensagem_editada = parse_message(mensagem, nome_paciente, dia_da_semana, data_agendamento_formato_br, hora_inicial)   
    
    return mensagem_editada, telefone_cliente, nome_paciente
    
def parse_message(mensagem, nome_paciente, dia_semana, data_agendamento, horario_agendamento):
    mensagem = mensagem.replace("{{NOME_PACIENTE}}", nome_paciente)
    mensagem = mensagem.replace("{{DIA_SEMANA}}", dia_semana)    
    mensagem = mensagem.replace("{{DATA_AGENDAMENTO}}", data_agendamento)
    mensagem = mensagem.replace("{{HORARIO_AGENDAMENTO}}", horario_agendamento)
    return mensagem 
        
                        




get_login()
