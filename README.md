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

O painel em `/plataforma/` abre diretamente a agenda diária para os perfis com acesso à agenda, no fuso `America/Cuiaba`. A visão geral continua disponível no menu. Para agendar, clique em um horário livre e escolha o paciente; sala, início e término vêm preenchidos. O profissional continua obrigatório. Tratamento adquirido e sessão são opcionais e não são consumidos ao agendar.

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
- Agenda diária em `/plataforma/agenda/`, com linha do tempo vertical, salas em colunas, horários e cabeçalhos fixos na rolagem, navegação por data e filtros por piso/sala. Busca e filtro por profissional atenuam os demais atendimentos, mantendo a ocupação visível. O cancelamento exige confirmação e POST com CSRF; preserva o registro, a sessão original e as evoluções, liberando a sessão não realizada. Atendimentos realizados não podem ser reagendados.
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

As migrações `0003` e `0004` preservam o catálogo antigo renomeando `Treatment` para `TreatmentCompany`. Os agendamentos anteriores mantêm seu vínculo com o catálogo em `Appointment.treatment_company`, sem inventar aquisições ou quantidades compradas. Tratamento e sessão são opcionais nos novos agendamentos. Itens antigos começam com preço zero, que pode ser atualizado em “Editar tratamento”.

## Agenda diária e disponibilidade

O administrador cadastra pisos, salas e bloqueios em **Configurações → Salas e disponibilidade** (`/plataforma/agenda/configuracoes/`). Cada sala tem piso, cor e horário diário de abertura/encerramento, no mesmo dia. Ausências, almoço, manutenção, feriados e intervalos de vários dias são registrados como bloqueios datados. Desativar pisos e salas impede novos agendamentos e mantém o histórico; salas inativas com atendimento ou bloqueio na data continuam aparecendo.

No cadastro de bloqueio, **Repetir bloqueio** permite selecionar **Somente neste período**, **Todos os dias** ou **Dias da semana** (por exemplo, segunda, quarta e sexta, das 12h às 14h). A data de início define quando a regra começa; o horário final pertence ao mesmo dia nas regras recorrentes. **Repetir até** é opcional e inclusivo. A regra é armazenada uma vez, sem gerar registros infinitos, e suas ocorrências são calculadas para cada data da agenda. Novas regras e edições são rejeitadas se atingirem atendimentos já existentes. Desativar a regra libera suas ocorrências. A migração `0008` preserva bloqueios anteriores como pontuais.

Atendimentos não realizados podem ser arrastados para outra sala/horário, com encaixe de 15 minutos e prévia do destino. A duração é preservada. No toque, use o marcador de arrastar no canto do cartão; o restante da agenda continua permitindo rolagem. Horários fechados, bloqueios e conflitos são revalidados no servidor; uma tentativa recusada mantém o atendimento original e explica o motivo. Alterações feitas por outra pessoa desde o carregamento da página também impedem uma movimentação desatualizada. A edição por formulário permanece acessível pelo teclado.

As migrações `0006` e `0007` adicionam essa estrutura e o término dos agendamentos. O término dos registros anteriores é calculado com a duração do catálogo; na ausência de catálogo, usa 30 minutos. Não são criadas salas, pisos ou aquisições fictícias. Registros anteriores sem sala aparecem em **Sem sala definida** e devem receber uma sala ao serem editados. Para atualizar outra instalação, execute `python manage.py migrate`.

O servidor valida início/término, funcionamento, bloqueios e sobreposição de sala, paciente ou profissional. Períodos adjacentes são permitidos. Agendamento, cancelamento e configuração de disponibilidade bloqueiam a linha da clínica em transação e revalidam o estado atual antes de salvar. MySQL é o banco configurado para execução; os testes isolados usam SQLite, que não valida a concorrência de locks de linha do MySQL.

Os seletores pesquisam no servidor em páginas de 20 resultados, com debounce e cancelamento de requisições antigas. Pacientes mostram nascimento e telefone; tratamentos mostram a aquisição e duração. A pesquisa de tratamentos restringe os resultados às aquisições ativas do paciente, preservando o fluxo de sessões existente. Use setas/Enter para selecionar e Escape para fechar a lista. Tratamento, sessão e observações ficam em uma seção opcional. A duração sugerida só é aplicada ao clicar em **Usar duração sugerida**, preservando horários manuais.

A pesquisa por nome também está disponível nos demais seletores da aplicação, incluindo pisos, salas, profissionais, filtros, perfis e campos adicionados dinamicamente aos pacotes. Esses seletores filtram as opções já autorizadas pelo formulário; pacientes, tratamentos e sessões da agenda continuam usando pesquisa paginada no servidor. Tratamentos com sessões livres aparecem primeiro, em ordem decrescente de disponibilidade; os sem sessões livres permanecem visíveis com um destaque **0 sessões disponíveis**. Disponibilidade significa sessões não realizadas e não reservadas em outro atendimento; na edição, a sessão do próprio atendimento é considerada disponível.

O agendamento possui uma **Data** e os campos de hora **Início** e **Fim**, acompanhados da duração calculada. O botão **Usar duração sugerida: 60 min**, por exemplo, define o fim como início + 60 minutos. Alterar um tratamento ou o início não sobrescreve o fim manualmente; é preciso aplicar a sugestão. O servidor calcula os instantes a partir desses campos no fuso da clínica, com validação de início/fim no mesmo dia.

Verificação opcional em Chromium, com banco isolado e sem dados de demonstração na aplicação:

```powershell
python -m pip install playwright
python -m playwright install chromium
python manage.py test tools.verify_agenda_ui --settings=config.test_settings
```

Esse fluxo cobre desktop e celular, rolagem com referências fixas, clique com preenchimento automático, busca por teclado, criação sem tratamento, edição com duração manual, cancelamento e cadastro de piso. Também verifica bloqueio recorrente, arrastar/soltar com mouse e toque, rejeição de um destino bloqueado, pesquisa em seletores comuns e dinâmicos, destaque de tratamentos sem sessões e sugestão de 60 minutos. Capturas de tela são gravadas na pasta temporária do sistema.

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
