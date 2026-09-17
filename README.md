# Chorompo

Plataforma Django para clínicas.

## Executar

O ambiente precisa das dependências Django, python-dotenv e do driver MySQL usado pelo projeto. Configure no `.env` as variáveis `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT` e `SECRET_KEY`.

`SECRET_KEY` deve ser uma chave aleatória, privada e persistente: ela assina as sessões e os links de confirmação. O ambiente local já recebeu uma chave gerada. Não publique o `.env`.

```powershell
python manage.py migrate
python manage.py runserver
```

Abra `http://127.0.0.1:8000/cadastro/` para iniciar ou retomar o cadastro pelo e-mail da clínica. O cadastro direto da empresa continua em `/empresas/cadastro/`.

## Fluxo de cadastro

1. E-mail novo: cadastro de `Company`, seguido do perfil do administrador.
2. Clínica existente sem nenhum `CompanyMembership`: confirmação do e-mail por link com validade de uma hora, seguida do perfil do administrador. A sessão que acabou de cadastrar a clínica pode continuar diretamente.
3. Clínica com qualquer vínculo de usuário, inclusive inativo: encaminhamento ao login; não é permitido recriar o administrador inicial.
4. O perfil cria `User`, `CompanyMembership` com papel `ADMIN` e `Employee` na mesma transação. A senha usa o mecanismo de hash e os validadores do Django. O administrador da clínica não recebe acesso de superusuário ao Django Admin.
5. Login automático e configuração inicial em `/integracao/`. Após confirmar os dados da clínica, `onboarding_completed` é persistido e o usuário entra no painel. Se sair antes de concluir, volta à integração no próximo acesso.

O login em `/entrar/` usa **nome de usuário e senha** escolhidos no perfil.

## Módulos base

O painel em `/plataforma/` oferece listagem e cadastro de pacientes, tratamentos, agendamentos e funcionários. A agenda inicial apresenta os atendimentos em uma lista por data, no fuso `America/Cuiaba`. Para um novo agendamento, selecione o paciente, seu tratamento adquirido, uma sessão disponível e um profissional ativo da clínica. Agendar não consome a sessão.

O cadastro de funcionário cria seu usuário, perfil de acesso e `Employee`, sem trocar a sessão do administrador. Os dados e as opções dos formulários são filtrados pela clínica vinculada ao usuário autenticado; enviar outro identificador de empresa não muda esse vínculo.

| Perfil | Acesso |
| --- | --- |
| Administrador | Pacientes, tratamentos, agenda, funcionários e financeiro |
| Recepção | Pacientes e agenda |
| Profissional | Pacientes, tratamentos e agenda |
| Financeiro | Visão financeira |

## Interface e gestão

- Painel com indicadores reais, menu lateral e layout adaptado para celular.
- Busca por nome/identificação em pacientes e funcionários, e por nome em catálogo e aquisições. A paginação mantém os filtros.
- Edição de pacientes e dos dados pessoais dos funcionários pela ação **Editar**. O perfil de acesso do funcionário é preservado; o catálogo mantém sua edição existente.
- Agenda semanal em `/plataforma/agenda/`, com busca, seleção de semana e profissional, criação e reagendamento. Após salvar, a agenda abre na semana escolhida. A remoção exige confirmação e POST com CSRF; libera sessões não realizadas e preserva evoluções clínicas. Atendimentos realizados não podem ser reagendados.
- Financeiro em `/plataforma/financeiro/`, para administradores e perfil Financeiro: valores de vendas registradas, ticket médio, aquisições, sessões vendidas, gráfico mensal e listagem com busca e período. Os indicadores usam os totais históricos das aquisições, incluindo inativas. Não representam recebimentos nem saldo em caixa, pois não há registro de pagamentos nesta versão.

Essas melhorias não exigem novas migrações de banco de dados.

## Catálogo, aquisições e acompanhamento

Na sidebar, **Configurações** reúne funcionários e catálogo da clínica em um grupo expansível, filtrado pelas permissões do usuário. O botão **Cadastro de tratamentos** fica dentro do catálogo. A listagem de tratamentos dos pacientes abre uma página própria de aquisição pelo botão **Novo tratamento do paciente**, em `/plataforma/tratamentos/pacientes/novo/`. Pacientes, funcionários e agenda continuam usando janelas modais para criar e editar registros. As URLs de edição também continuam acessíveis como páginas independentes.

Na aquisição, o botão **Adicionar tratamento** permite montar um pacote para um paciente com até 20 tratamentos diferentes. Cada item possui quantidade de sessões e desconto próprios. Um `TreatmentPackage` agrupa a compra, e cada item continua sendo um `Treatment` com suas próprias sessões e evoluções. O resumo do pacote mostra o total consolidado e os subtotais. Se algum item falhar, nenhuma parte do pacote é salva. Compras individuais anteriores permanecem disponíveis.

- `TreatmentCompany`: catálogo em `/plataforma/tratamentos/`, com criação e edição de nome, descrição, duração, preço por sessão, custos fixo e variável por sessão e desconto máximo (0 a 100%).
- `Treatment`: aquisição de um item do catálogo por um paciente em `/plataforma/tratamentos/pacientes/`. Guarda o nome e a descrição adquiridos, quantidade, desconto e valor total no momento da aquisição. Alterações posteriores no catálogo não mudam essas aquisições. O total é preço por sessão × quantidade, descontado o percentual informado, com arredondamento para centavos.
- `TreatmentSession`: uma linha para cada sessão comprada, numerada dentro da aquisição. A aquisição e suas sessões são criadas em uma transação; a quantidade aceita é de 1 a 1.000. A página da aquisição mostra sessões compradas, realizadas, disponíveis e seus agendamentos. `session_held` vale 0 (disponível) ou 1 (realizada), e `date` guarda a data da realização.
- `EvolutionOfTreatment`: histórico por sessão, com observações obrigatórias, data e profissional autenticado. Marcar “Registrar realização desta sessão” consome aquela sessão uma única vez. Anotações complementares podem ser acrescentadas sem novo consumo. Datas futuras são rejeitadas. Registros são acrescentados ao histórico, sem edição ou exclusão pela interface.

As operações de aquisição, evolução e agendamento ficam em `chorompo/treatment_services.py`. O consumo e o agendamento bloqueiam as linhas da aquisição e da sessão dentro de transações, revalidando a disponibilidade para evitar reenvios que consumam a sessão novamente. Os formulários e as páginas restringem todos os vínculos à clínica autenticada.

As migrações `0003` e `0004` preservam o catálogo antigo renomeando `Treatment` para `TreatmentCompany`. Os agendamentos anteriores mantêm seu vínculo com o catálogo em `Appointment.treatment_company`, sem inventar aquisições ou quantidades compradas. Novos agendamentos exigem também `Appointment.treatment` e `Appointment.session`. Itens antigos começam com preço zero, que pode ser atualizado em “Editar tratamento”.

## Confirmação de e-mail

Em desenvolvimento, o backend padrão `chorompo.mail_backends.ReadableConsoleEmailBackend` escreve o texto original dos e-mails no terminal do `runserver`, com cada link completo em uma linha, sem codificação MIME. Copie o endereço inteiro, incluindo a barra final. Se seu `.env` define o backend de console padrão do Django, substitua-o por este backend para evitar URLs quebradas por `quoted-printable`. Para entregar mensagens reais, configure um serviço SMTP no `.env`:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.seu-provedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=seu-usuario
EMAIL_HOST_PASSWORD=sua-senha
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=Chorompo <cadastro@seu-dominio.com>
```

Links usados não permitem criar outro administrador após existir um vínculo. Solicitações repetidas de e-mail na mesma sessão têm intervalo mínimo de um minuto.

## Testes

```powershell
python manage.py test --settings=config.test_settings
python manage.py check
```

Os testes usam SQLite em memória e e-mails em memória, sem alterar o MySQL ou enviar mensagens. Cobrem cadastro, normalização, senhas, retomada por e-mail, integração, permissões, isolamento entre clínicas, rollback e proteção CSRF. As migrações são aplicadas separadamente ao MySQL configurado.
