# Robô de Encaminhamento no 1Doc

Automação em Python que encaminha comprovantes de pagamento no sistema **1Doc**. O robô lê os PDFs salvos na pasta do dia, localiza cada processo correspondente no 1Doc, reabre o que estiver arquivado e encaminha para a unidade de destino com o texto padrão, o anexo e as opções de arquivamento marcadas.

Ele repete exatamente os cliques que seriam feitos manualmente, usando o login do próprio usuário, e gera um relatório no final.

## Sumário

- [Como funciona](#como-funciona)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Uso](#uso)
- [Padrão de nomes](#padrão-de-nomes)
- [Arquivos gerados](#arquivos-gerados)
- [Segurança](#segurança)
- [Solução de problemas](#solução-de-problemas)

## Como funciona

1. **Define a data de referência:** o dia útil anterior. Na segunda-feira, usa a sexta.
2. **Encontra a pasta do dia** no caminho `Z:\secretaria\ANO\MÊS\DD de mês`, por exemplo `Z:\secretaria\2026\SETEMBRO\21 de setembro`. Aceita variações de maiúsculas, acentos, zero à esquerda e espaços extras.
3. **Para cada PDF da pasta:**
   1. Interpreta o nome do arquivo (tipo, número e ano).
   2. Pesquisa `número/ano` no 1Doc e abre o resultado cujo tipo corresponde ao arquivo.
   3. Se o processo estiver arquivado, clica em **Reabrir** e confirma.
   4. Clica em **Encaminhar** e seleciona a unidade de destino.
   5. Escreve o texto padrão, com "bom dia" ou "boa tarde" conforme o horário.
   6. Marca **Arquivar** e **Arquivar + Parar de acompanhar**.
   7. Anexa o PDF.
   8. Clica em **Encaminhar** e confirma na janela "Confirma?", conferindo antes se o tipo mostrado na janela bate com o arquivo.
4. **Gera um relatório** com o que foi encaminhado, o que foi reaberto e o que ficou pendente.

Sempre que houver dúvida (nome fora do padrão, processo não encontrado, mais de um resultado, tipo divergente), o robô **não altera nada** e envia o arquivo para a lista de pendências.

## Requisitos

- Windows 10 ou 11
- [Python 3.9 ou superior](https://www.python.org/downloads/), instalado com a opção **Add Python to PATH**
- Microsoft Edge (já incluído no Windows)
- Biblioteca [Playwright](https://playwright.dev/python/)
- Acesso de leitura à pasta de rede dos comprovantes
- Usuário e senha do 1Doc com permissão para reabrir e encaminhar os documentos

## Instalação

1. Baixe este repositório (botão **Code > Download ZIP**) e extraia numa pasta, por exemplo `Documentos\Robo 1Doc`.
2. Dê dois cliques em `instalar.bat` e aguarde o fim da instalação.

Ou, pelo Prompt de Comando:

```bat
python -m pip install --upgrade playwright
```

Não é necessário rodar `playwright install`, pois o robô usa o Edge já instalado.

## Configuração

Abra `robo_1doc.py` num editor de texto e ajuste o bloco `CONFIGURACOES` no início do arquivo:

| Variável | O que é | Exemplo |
|---|---|---|
| `URL_1DOC` | Endereço do 1Doc usado no navegador | `https://cacador.1doc.com.br/` |
| `PASTA_BASE` | Pasta que contém as pastas de ano | `Z:\secretaria` |
| `BUSCA_UNIDADE` | Texto digitado no campo "Para" | `Arquivo saude` |
| `OPCAO_UNIDADE` | Texto exato da unidade na lista | `Arquivo Saúde - Arquivo Saúde` |
| `TEXTO_MENSAGEM` | Corpo da mensagem (`{saudacao}` vira "bom dia" ou "boa tarde") | `Prezados, {saudacao}!\nSegue comprovante de pagamento.` |
| `MODO_CONFERENCIA` | Se `True`, pede confirmação antes de cada encaminhamento | `True` |
| `TIPOS` | Como cada tipo de arquivo aparece no 1Doc | ver código |
| `ESPERA_UPLOAD_SEG` | Tempo máximo de espera pelo upload do anexo | `60` |

## Uso

Dê dois cliques em `executar.bat`.

Na primeira execução, o Edge abre e pede login no 1Doc. Entre normalmente, volte à janela do Prompt de Comando e aperte **Enter**. O login fica salvo para as próximas vezes.

Para processar uma data específica:

```bat
executar.bat 24/09/2026
```

### Modo conferência

Com `MODO_CONFERENCIA = True`, o robô preenche todo o formulário e para na janela de confirmação, perguntando:

```
>>> Confirmar o encaminhamento? [s = sim / n = nao]:
```

Digite `s` para confirmar ou `n` para cancelar (o arquivo vai para as pendências). Recomenda-se manter esse modo ligado nas primeiras semanas e só depois mudar para `False`.

> Não mexa na janela do Edge do robô enquanto ele estiver trabalhando.

## Padrão de nomes

Os arquivos devem seguir o formato `Tipo Número-Ano.pdf`:

| Arquivo | Tipo | Pesquisa no 1Doc |
|---|---|---|
| `Memorando 20.185-26.pdf` | Memorando | `20185/2026` |
| `Protocolo 37270-26.pdf` | Protocolo | `37270/2026` |
| `Proc ADM 4.663-26.pdf` | Processo Administrativo | `4663/2026` |
| `Despesa Extra 15.689-26.pdf` | Despesa Extra | `15689/2026` |

O ponto de milhar é opcional, o ano pode ter 2 ou 4 dígitos e maiúsculas ou minúsculas são indiferentes. Arquivos fora desse padrão não são processados e aparecem como pendentes.

## Arquivos gerados

| Arquivo ou pasta | Conteúdo |
|---|---|
| `relatorios/relatorio_AAAA-MM-DD_exec_....csv` | Resultado de cada arquivo: encaminhado, reaberto, pendente ou erro |
| `relatorios/prints_erros/` | Captura de tela de cada arquivo que deu problema |
| `processados.csv` | Histórico do que já foi encaminhado, para evitar envio em duplicidade |
| `perfil_navegador/` | Sessão salva do Edge usada pelo robô |

## Segurança

- O robô **não armazena senha**: o login é feito manualmente e fica apenas na sessão local do navegador.
- Ele acessa somente o que o usuário já pode acessar e não envia dados para nenhum outro serviço.
- **Nunca publique** as pastas `perfil_navegador/` e `relatorios/` nem o arquivo `processados.csv`, pois contêm a sessão do 1Doc e dados de processos. O `.gitignore` deste repositório já os exclui.
- Antes de usar em produção, confirme com a TI e com a chefia que a automação é permitida, e se possível teste primeiro num ambiente de treinamento do 1Doc.

## Solução de problemas

| Situação | O que fazer |
|---|---|
| `'python' não é reconhecido` | Reinstale o Python marcando **Add Python to PATH** |
| "Nenhuma pasta encontrada para essa data" | Confira `PASTA_BASE` e o nome das pastas de ano, mês e dia |
| "Mais de uma pasta de dia" | Há pastas duplicadas para a mesma data; deixe apenas uma |
| "Processo não encontrado na busca" | Verifique o número e o tipo no nome do arquivo |
| "Unidade não apareceu na lista" | Ajuste `BUSCA_UNIDADE` e `OPCAO_UNIDADE` |
| "Não achei o campo de pesquisa" | Faça a pesquisa manualmente quando o robô pedir e aperte Enter |
| O Edge não abre | Feche outras janelas do Edge abertas pelo robô e tente de novo |

Em qualquer pendência, consulte o print salvo em `relatorios/prints_erros/`.

## Estrutura do projeto

```
Robo 1Doc/
├── robo_1doc.py     # script principal
├── instalar.bat     # instala o Playwright
├── executar.bat     # executa o robô
├── LEIAME.txt       # instruções rápidas
├── README.md
└── .gitignore
```
