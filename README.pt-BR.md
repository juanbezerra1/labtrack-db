# labtrack-db

[![CI](https://github.com/juanbezerra1/labtrack-db/actions/workflows/ci.yml/badge.svg)](https://github.com/juanbezerra1/labtrack-db/actions/workflows/ci.yml)

**Um esquema PostgreSQL para um laboratório de biossinais, feito para ser lido, executado e quebrado.**

O laboratório é inventado (participantes, visitas de estudo, equipamentos e suas calibrações, gravações de EMG e EEG,
tentativas e as características calculadas a partir delas) e cada linha também. O que é real é a engenharia: um esquema
cujas restrições recusam dados ruins, um executor de migrações pequeno, um gerador de dados determinístico em quatro
tamanhos, consultas didáticas, lições de EXPLAIN, um esquema estrela com exportação em CSV para dashboards e uma
suíte de testes que roda contra um PostgreSQL de verdade. Eu trabalho com experimentos de EMG e EEG, então o domínio
me é familiar; nenhum dado vem desses experimentos.

English: [README.md](README.md)

## Visão geral

| | |
|---|---:|
| Tabelas no esquema `lab` | 13 |
| Chaves estrangeiras entre elas | 13 |
| Tipos enumerados | 6 |
| Migrações | 13 |
| Consultas didáticas | 12 |
| Lições de EXPLAIN | 8 |
| Verificações de qualidade dos dados | 12 |
| Tamanhos de dados sintéticos | 4 |

Se você tem só cinco minutos, leia nesta ordem: o [diagrama do esquema](#o-esquema),
[`docs/design-notes.md`](docs/design-notes.md) (em inglês: por que o esquema é assim, e dez armadilhas em que eu caí),
uma das [consultas](queries/) (cada uma é comentada como uma aula) e
[`tests/test_constraints.py`](tests/test_constraints.py).

## Início rápido

Você precisa de Python 3.10 ou mais novo e de um servidor PostgreSQL 16. O jeito mais fácil é o do
[`docker-compose.yml`](docker-compose.yml):

```bash
git clone https://github.com/juanbezerra1/labtrack-db.git
cd labtrack-db
docker compose up -d --wait        # PostgreSQL 16 em localhost:5432 (usuário, senha e banco: labtrack)
python3 -m venv .venv              # Windows: py -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1   (cmd.exe: .venv\Scripts\activate.bat)
python -m pip install -e .         # Windows: py -m pip install -e .
labtrack migrate                   # cria o esquema
labtrack seed --scale small        # dados sintéticos, uns 10 segundos
labtrack check                     # as verificações de qualidade dos dados
labtrack query 10                  # uma das consultas didáticas
```

Os dois últimos comandos imprimem isto (os dados são os mesmos em qualquer máquina):

```console
$ labtrack check
  ok   room_double_booked
  ok   visits_out_of_order
  ok   completed_without_recording
  ok   recording_outside_session
  ok   recording_of_uncompleted_session
  ok   trial_beyond_recording
  ok   feature_for_missing_channel
  ok   feature_of_wrong_modality
  ok   channel_count_mismatch
  ok   session_after_withdrawal
  ok   device_used_after_retirement
  ok   researcher_not_employed
12 of 12 checks passed
```

```console
$ labtrack query 10
-- Query 10: does the feedback lower force variability, and does it depend on the group?
group_label  | values_used | feedback_on | feedback_off | difference
-------------+-------------+-------------+--------------+-----------
control      |        1559 |       4.342 |        4.517 |     -0.175
intervention |        1279 |       3.717 |        4.539 |     -0.821
(2 rows)
```

A consulta 10 pergunta se o feedback reduz a variabilidade da força, por grupo. Reduz, e mais no grupo de
intervenção: é um dos efeitos que o gerador planta de propósito
([abaixo](#o-que-foi-plantado-nos-dados)).

Coisas que mudam na sua máquina:

* **A porta 5432 está ocupada.** Suba o servidor com `LABTRACK_PORT=5433 docker compose up -d --wait` (no PowerShell:
  `$env:LABTRACK_PORT = "5433"; docker compose up -d --wait`) e passe
  `--dsn postgresql://labtrack:labtrack@localhost:5433/labtrack` antes do nome do comando
  (`labtrack --dsn ... status`), ou defina uma vez a variável de ambiente `LABTRACK_DSN`.
* **Sem Docker.** Use um PostgreSQL 16 que você já tenha, com um usuário que possa criar bancos:
  `export LABTRACK_DSN=postgresql://USUARIO:SENHA@localhost:5432/labtrack` (no PowerShell:
  `$env:LABTRACK_DSN = "..."`), depois `labtrack createdb` e `labtrack migrate`. Não precisa do `psql`.
* **O PowerShell não ativa o ambiente** ("running scripts is disabled on this system"). Rode uma vez
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e abra uma janela nova, ou use o `cmd.exe` e
  `.venv\Scripts\activate.bat`.

## O esquema

```mermaid
erDiagram
    study ||--o{ enrollment : "has"
    participant ||--o{ enrollment : "joins"
    enrollment ||--o{ session : "session_enrollment_fk"
    researcher ||--o{ session : "runs"
    researcher ||--o{ calibration : "performs"
    device ||--o{ calibration : "has"
    session ||--o{ session_device : "books"
    device ||--o{ session_device : "is booked"
    session_device ||--o{ recording : "recording_session_device_fk"
    recording ||--o{ channel : "has"
    recording ||--o{ trial : "has"
    trial ||--o{ trial_feature : "has"
    feature_def ||--o{ trial_feature : "defines"

    study {
        integer study_id PK
        text code UK
        text title
        date started_on
        date ended_on
    }
    participant {
        integer participant_id PK
        text code UK
        smallint birth_year
        date consent_signed_on
        date withdrawn_on
    }
    enrollment {
        integer study_id PK, FK
        integer participant_id PK, FK
        text group_label
        date enrolled_on
    }
    researcher {
        integer researcher_id PK
        text full_name
        researcher_role role
        text email UK
    }
    device {
        integer device_id PK
        device_kind kind
        text serial_no UK
        text home_room
        date retired_on
    }
    calibration {
        integer calibration_id PK
        integer device_id FK
        date performed_on
        integer performed_by FK
        boolean passed
        date valid_until
    }
    session {
        bigint session_id PK
        integer study_id FK
        integer participant_id FK
        integer researcher_id FK
        smallint visit_no
        text room
        timestamptz starts_at
        timestamptz ends_at
        session_status status
        tstzrange during "generated"
    }
    session_device {
        bigint session_id PK, FK
        integer device_id PK, FK
    }
    recording {
        bigint recording_id PK
        bigint session_id FK
        integer device_id FK
        modality modality
        smallint block_no
        timestamptz recorded_at
        char(64) sha256 UK
        qc_status qc
    }
    channel {
        bigint recording_id PK, FK
        smallint channel_no PK
        text label
    }
    trial {
        bigint trial_id PK
        bigint recording_id FK
        integer trial_no
        text condition
        boolean valid
    }
    feature_def {
        smallint feature_id PK
        modality modality
        text name
    }
    trial_feature {
        bigint trial_id PK, FK
        smallint channel_no PK
        smallint feature_id PK, FK
        float8 value
    }
```

Só as colunas principais estão desenhadas; o [dicionário de dados](docs/data-dictionary.md) (em inglês) lista todas.
Ele é gerado a partir dos `COMMENT`s das migrações, e um teste falha quando o arquivo fica desatualizado. `PK` é uma
chave primária, `FK` uma chave estrangeira e `UK` uma chave natural única.

Três camadas: `lab` guarda os dados (as tabelas acima, quatro views `v_` para as perguntas do dia a dia e uma view
materializada), `bi` guarda oito views somente leitura em esquema estrela para dashboards (veja
[Dashboards](#dashboards)) e `public` guarda só a tabela de controle das migrações. Dois papéis dão privilégio mínimo:
`labtrack_reader` lê tudo e não altera nada; `labtrack_writer` altera linhas, mas não o esquema.

### Regras que o banco impõe

Uma restrição (constraint) é uma regra que o banco se recusa a deixar quebrar, não importa o que a aplicação faça.

| Regra | Mecanismo | Nome |
|---|---|---|
| Uma sessão só existe para um participante inscrito naquele estudo | chave estrangeira composta para `enrollment` | `session_enrollment_fk` |
| Uma gravação só usa um aparelho reservado para a sua própria sessão | chave estrangeira composta para `session_device` | `recording_session_device_fk` |
| Duas sessões ativas nunca se sobrepõem na mesma sala | restrição de exclusão (GiST, `btree_gist`) | `session_room_no_overlap` |
| Uma tentativa rejeitada tem motivo e uma válida não tem | `CHECK` | `trial_reason_iff_rejected` |
| Nenhuma sessão antes do consentimento, da inscrição ou do início do estudo; nenhuma depois da desistência ou do fim do estudo | gatilho `BEFORE`, porque um `CHECK` não lê outras tabelas | `session_before_consent`, `session_before_enrollment`, `session_outside_study`, `session_after_withdrawal` |

O gatilho levanta `check_violation` (SQLSTATE 23514) e dá à regra o nome de restrição, então um cliente o trata como um
`CHECK` que falhou. Uma restrição só protege as escritas na própria tabela: se a data de desistência de um participante
for movida para trás depois que sessões foram marcadas, nada dispara. É por isso que existe o `labtrack check`, com
consultas que sempre devem não achar nada. O [`docs/design-notes.md`](docs/design-notes.md) explica essas escolhas e as
armadilhas por trás delas (uma coluna gerada é calculada antes dos `CHECK`s, um `CHECK` deixa passar `NULL`,
`NaN = NaN` é verdadeiro…). Em [`tests/test_constraints.py`](tests/test_constraints.py) cada restrição `CHECK`,
`UNIQUE` e de exclusão tem um teste que precisa fazê-la falhar, e um teste falha quando alguém adiciona uma restrição
sem teste.

## Tamanhos

`labtrack seed --scale TAMANHO` enche as tabelas com dados sintéticos. É determinístico: o mesmo tamanho e a mesma data
de `--as-of` dão as mesmas linhas em qualquer máquina e em qualquer versão do PostgreSQL (sem `random()`, sem `now()`;
os números vêm do `md5()` de uma chave de texto). O padrão é `small`.

| Tamanho | Participantes | Sessões | Gravações | Tentativas | Valores de características | Tamanho do banco | Tempo da carga |
|---|---:|---:|---:|---:|---:|---:|---:|
| `tiny` | 20 | 86 | 152 | 4.257 | 105.480 | 19 MB | 5 s |
| `small` | 60 | 261 | 460 | 12.907 | 314.368 | 37 MB | 10 s |
| `medium` | 200 | 909 | 1.634 | 45.806 | 1.105.112 | 106 MB | 30 s |
| `large` | 1.800 | 8.412 | 15.008 | 421.237 | 10.378.232 | 912 MB | 4 min 19 s |

As contagens de `tiny`, `small` e `medium` são fixadas por arquivos de referência (golden), e um teste faz a carga duas
vezes e compara um resumo md5 de cada tabela. O `large` foi medido uma vez e não faz parte da suíte de testes. O tamanho
do banco e o tempo foram medidos na máquina descrita na seção [Laboratório de EXPLAIN](#laboratório-de-explain); na sua
serão diferentes. As lições de EXPLAIN precisam de `medium` ou maior, porque o planejador escolhe outros planos em
tabelas pequenas.

## O que foi plantado nos dados

O gerador planta algumas coisas de propósito, para que as consultas tenham o que achar. **Não é ciência**: não leia os
números como evidência de nada.

* **Três efeitos.** O feedback reduz a variabilidade da força, mais no grupo de intervenção: consulta 10. Depois da
  tarefa de fadiga do EMG-03 a frequência mediana do EMG cai e o RMS sobe. Um estímulo visual grande reduz a potência
  alfa, que de qualquer modo é mais forte nos canais occipitais. Nenhuma consulta numerada olha os dois últimos, então
  são um exercício: escreva a consulta.
* **Aparelhos com uma história.** Todo aparelho é calibrado a cada 90 dias e cada calibração vale por 120 dias, exceto
  estes. A terceira coluna é o que `lab.v_device_status` diz no "hoje" da carga, 2026-10-31.

| Aparelho | O que foi plantado | Situação em 2026-10-31 |
|---|---|---|
| `SN-EMG-03`, `SN-DYN-03`, `SN-EEG-02` | pularam rodadas de calibração em 2024 e 2025 | `ok` |
| `SN-DYN-02`, `SN-EEG-04`, `SN-STM-02` | deixaram de ser calibrados | `overdue` |
| `SN-EMG-06` | deixou de ser calibrado | `due_soon` |
| `SN-EMG-08` | o amplificador mais novo, nunca calibrado | `never_calibrated` |
| `SN-STM-06` | um estimulador que foi aposentado | `retired` |

A consulta 4 acha as gravações feitas num dia em que o aparelho não tinha calibração válida. De `small` para cima ela
acha exatamente os três aparelhos que pularam rodadas (o `tiny` é pequeno demais para pegar os três):

```console
$ labtrack query 4 --variant not_exists
-- Query 4: recordings made with a device that was not calibrated that day  [variant not_exists]
serial_no | kind          | recordings | first_day  | last_day
----------+---------------+------------+------------+-----------
SN-DYN-03 | dynamometer   |         25 | 2024-11-13 | 2025-03-17
SN-EMG-03 | emg_amplifier |         16 | 2025-05-12 | 2025-09-22
SN-EEG-02 | eeg_amplifier |          3 | 2025-04-14 | 2025-08-25
(3 rows)
```

## Consultas didáticas

`labtrack query` lista, `labtrack query N` executa uma e `labtrack query N --show` imprime o SQL antes. Cada arquivo em
[`queries/`](queries/) começa com a pergunta e os conceitos que ensina, seguidos de notas sobre como lê-lo. Quando uma
consulta tem variantes (a mesma resposta escrita de jeitos diferentes), um teste confere que elas devolvem as mesmas
linhas.

| # | Pergunta | O que ensina | Variantes |
|---:|---|---|---|
| 1 | as dez sessões concluídas mais recentes | `JOIN ... USING`, desempate no `ORDER BY`, `AT TIME ZONE` | |
| 2 | como andam os estudos? | `GROUP BY ROLLUP`, `FILTER`, `NULLIF`, divisão inteira contra `numeric` | |
| 3 | inscritos que nunca concluíram uma sessão | anti-joins e a armadilha do `NOT IN` com `NULL` | `left_join`, `not_exists`, `not_in` |
| 4 | gravações feitas com um aparelho que não estava calibrado naquele dia | join por intervalo, `NOT EXISTS`, fusos horários | `not_exists`, `left_join` |
| 5 | dias entre as visitas | função de janela `LAG` | |
| 6 | horas gravadas mês a mês, com total acumulado | `SUM() OVER`, view materializada | |
| 7 | os três participantes mais ativos de cada estudo | top-N por grupo | `window`, `lateral` |
| 8 | sequências de semanas movimentadas seguidas ("lacunas e ilhas") | lacunas e ilhas (gaps and islands) | |
| 9 | o que dá errado nas sessões, e fica mais quente nessas horas? | `jsonb`, `LATERAL` | |
| 10 | o feedback reduz a variabilidade da força, e isso depende do grupo? | agregação condicional, por que filtrar as tentativas válidas | |
| 11 | a última calibração aprovada de cada aparelho | a última linha por grupo, de três jeitos | `distinct_on`, `lateral`, `window` |
| 12 | a dispersão da amplitude RMS por canal | `percentile_cont ... WITHIN GROUP` | |

## Laboratório de EXPLAIN

Oito lições, cada uma com uma pergunta, os planos de duas ou três versões de uma consulta e o que observar.
`labtrack explain-lab` lista e `labtrack explain-lab N` executa uma num banco `medium` ou maior. Uma lição roda
dentro de uma transação que é desfeita no fim, então nunca altera seus dados nem seus índices (`CREATE INDEX` é
transacional no PostgreSQL). `--plans` também imprime o texto do próprio `EXPLAIN` do PostgreSQL.

Tempos de execução em milissegundos, no tamanho `large`:

| # | Lição | Tempo (ms) | O que observar |
|---:|---|---:|---|
| 1 | um índice para um filtro seletivo | 316,9 → 3,3 | a chave primária começa por `trial_id`, então um filtro por `feature_id` não a usa: `Seq Scan`, depois `Bitmap Index Scan` |
| 2 | uma função em volta da coluna esconde o índice | 1,6 → < 0,1 | `recorded_at::date = ...` não usa o índice; um intervalo sobre a coluna pura usa. A tabela é pequena, então vale o formato do plano, não o tempo |
| 3 | um índice que guarda a resposta (index-only scan) | 0,2 → 0,3 | os acessos à tabela (heap fetches) caem a zero. Com o cache quente o tempo quase não muda |
| 4 | um índice só para as linhas raras (índice parcial) | 37,2 → 6,9 | a lição também imprime o tamanho do índice parcial ao lado de um completo |
| 5 | nested loop ou hash join? Depende de quanto você pede | 0,2 / 2.151,0 | não é um ganho de velocidade: são duas perguntas diferentes, e o planejador escolhe uma estratégia de join para cada |
| 6 | ordenar na memória ou no disco (work_mem) | 148,3 / 163,6 / 45,0 | `external merge`, `quicksort`, `top-N heapsort`. A ordenação em memória não ganhou no relógio aqui; pedir dez linhas ganhou |
| 7 | quando o planejador erra a estimativa (colunas correlacionadas) | 1,7 → 1,4 | a estimativa ficava várias vezes abaixo do real até o `CREATE STATISTICS`; o tempo quase não mudou |
| 8 | a página 1500 de uma lista (OFFSET contra paginação por chave) | 7,2 → < 0,1 | o `OFFSET` produz 29.980 linhas e as joga fora; a paginação por chave vai direto à página |

Como esses números foram obtidos, e quanto confiar neles:

* Linux com 2 vCPUs e 7,8 GiB de RAM, PostgreSQL 16.15 com as configurações padrão (`shared_buffers` 128 MB,
  `work_mem` 4 MB), 10.378.232 valores de características. Mediana de 5 execuções depois de uma execução de
  aquecimento. Os números brutos, com o mínimo e o máximo de cada passo, estão em
  [`docs/measurements/explain-lab-large.json`](docs/measurements/explain-lab-large.json), e o
  [`scripts/measure_explain_lab.py`](scripts/measure_explain_lab.py) repete a medição na sua máquina.
* Tempos dependem da máquina e variam: três execuções separadas da medição inteira nesta máquina deram entre 290 e 348 ms
  no primeiro passo da lição 1.
  Leia as proporções, não os dígitos. A primeira execução depois de reiniciar o servidor pode ser bem mais lenta.
* Os testes verificam o **formato** de cada plano (um `Seq Scan` antes, um `Index Scan` depois), nunca uma duração, e só
  no PostgreSQL 16.

## Dashboards

O esquema `bi` tem oito views somente leitura em esquema estrela (três fatos, cinco dimensões).
`labtrack export --out PASTA` as grava como arquivos CSV (UTF-8, quebras de linha `LF`, `true` e `false`, célula vazia
para `NULL`) mais um arquivo `SHA256SUMS`, para Power BI, Excel ou pandas. A pasta [`exports/small/`](exports/small/)
tem a exportação do tamanho `small`, para você começar sem banco de dados; um teste confere que ela é exatamente o que a
carga atual produz.

| Arquivo | Linhas | O que é uma linha |
|---|---:|---|
| `dim_date.csv` | 2.192 | um dia do calendário |
| `dim_study.csv` | 3 | um estudo |
| `dim_participant.csv` | 60 | um participante |
| `dim_researcher.csv` | 12 | um pesquisador |
| `dim_device.csv` | 24 | um aparelho |
| `fact_session.csv` | 261 | uma sessão |
| `fact_recording.csv` | 460 | uma gravação |
| `fact_trial.csv` | 12.907 | uma tentativa |

`fact_trial` traz as medidas principais de cada tentativa como colunas, para que um relatório não precise pivotar a
tabela longa `trial_feature`. Cada medida pertence a uma modalidade: as tentativas das outras modalidades têm a célula
vazia ali. Os valores de EMG e EEG são a média dos canais da gravação.

| Coluna de `fact_trial` | Modalidade | Medida em `feature_def` | Unidade |
|---|---|---|---|
| `rms_mean_uv` | emg | `rms` | uV |
| `mnf_hz` | emg | `mnf` | Hz |
| `mdf_hz` | emg | `mdf` | Hz |
| `alpha_power_uv2` | eeg | `power_alpha` | uV^2 |
| `peak_force_n` | force | `peak_force` | N |
| `force_cv_pct` | force | `force_cv` | % |

`fact_recording.device_calibrated` é `false` para a gravação feita num dia em que nenhuma calibração aprovada do seu
aparelho valia: a consulta 04 como uma coluna que um relatório pode filtrar. No tamanho `small` ela é `false` em 44 das
460 gravações.

## Migrações

O esquema é construído por arquivos SQL numerados em [`migrations/`](migrations/), aplicados em ordem por um executor de
menos de 200 linhas ([`src/labtrack/migrate.py`](src/labtrack/migrate.py)), pequeno de propósito, para mostrar o que o
Flyway, o sqitch ou o Alembic fazem por você. Ele guarda o SHA-256 de cada arquivo aplicado e se recusa a continuar se
um deles foi editado depois.

```console
$ labtrack status
  0001  applied   schema_types_helpers
  0002  applied   people_and_equipment
  0003  applied   sessions_and_recordings
  0004  applied   features
  0005  applied   views
  0006  applied   bi_star_schema
  0007  applied   roles
  0008  applied   session_protocol_version
  0009  applied   backfill_protocol_version
  0010  applied   protocol_version_check
  0011  applied   protocol_version_validate
  0012  applied   recording_time_index
  0013  applied   bi_more_columns
```

Os arquivos 0008 a 0011 são um exemplo completo de como adicionar uma coluna `NOT NULL` a uma tabela em uso sem segurar
um bloqueio forte por muito tempo: adicionar a coluna, preenchê-la, criar um `CHECK` como `NOT VALID`, validá-lo (um
bloqueio mais fraco) e marcar `NOT NULL` (o PostgreSQL pula a varredura porque o `CHECK` validado já prova a regra).
Cada passo é um arquivo, porque uma migração é uma transação e seus bloqueios duram até ela terminar. O arquivo 0012
cria um índice com `CREATE INDEX CONCURRENTLY`, que não pode rodar dentro de uma transação, então o executor deixa um
arquivo optar por sair dela. O arquivo 0013 acrescenta colunas a duas views com `CREATE OR REPLACE VIEW`, que pode
anexar colunas mas nunca renomear nem mudar o tipo das que existem, então um relatório que já lê as views continua
funcionando. Não há migrações de volta (down): um banco em uso só avança.
O [`docs/design-notes.md`](docs/design-notes.md#migrations) tem o resto.

## Testes e CI

```bash
python -m pip install -e ".[dev]"      # Windows: py -m pip install -e ".[dev]"
export LABTRACK_TEST_DSN=postgresql://labtrack:labtrack@localhost:5432/postgres   # um usuário que possa criar bancos
pytest
```

No PowerShell, defina a variável com `$env:LABTRACK_TEST_DSN = "..."`.

Os testes criam seus próprios bancos com nomes aleatórios e os apagam no fim; nada do que você tem é tocado. Eles
cobrem as restrições, o executor de migrações e a sequência sem parada, o determinismo da carga, cada consulta didática
contra um resultado de referência, o formato do plano de cada lição, a integridade do esquema estrela e da exportação
CSV, o dicionário de dados, a linha de comando e este README: o diagrama, as tabelas de tamanhos, aparelhos e consultas e
cada bloco `$ labtrack ...` são comparados com o que o banco e a ferramenta realmente dizem.

O [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda `ruff` (lint e verificação de formato), `mypy` (estrito) e
`pytest` contra um serviço `postgres:16` em Python 3.10 e 3.13.

## Linha de comando

O `labtrack` é instalado por `python -m pip install -e .`; `python -m labtrack` (`py -m labtrack` no Windows) faz o mesmo. O `--dsn` vai antes do nome do
comando; sem ele a ferramenta usa `$LABTRACK_DSN` e depois `postgresql://labtrack:labtrack@localhost:5432/labtrack` (o
banco do Docker Compose).

| Comando | O que faz |
|---|---|
| `labtrack createdb` | cria o banco do DSN se ele não existir |
| `labtrack migrate` | aplica as migrações pendentes (`--to N` para depois da migração N) |
| `labtrack status` | lista as migrações e se cada uma foi aplicada; sai com 1 se um arquivo aplicado foi alterado |
| `labtrack seed` | enche o banco com dados sintéticos (`--scale`, `--as-of`, `--reset`) |
| `labtrack check` | roda as verificações de qualidade dos dados, cada uma deve não achar nada; sai com 1 se alguma achar |
| `labtrack query` | lista as consultas didáticas, ou executa uma (`N`, `--variant`, `--show`) |
| `labtrack explain-lab` | lista as lições de EXPLAIN, ou executa uma (`N`, `--plans`) |
| `labtrack export` | grava o esquema estrela `bi` como arquivos CSV (`--out`) |
| `labtrack dictionary` | imprime o dicionário de dados gerado a partir do catálogo (`--out`) |
| `labtrack counts` | a contagem de linhas de cada tabela de dados |

## Estrutura do repositório

```text
migrations/            arquivos SQL numerados: esquema, views, papéis e a mudança sem parada 0008 a 0012
seed/                  o gerador de dados sintéticos, em SQL
queries/               as consultas didáticas, cada uma comentada como uma aula
explain-lab/           as lições de EXPLAIN
docs/                  notas de projeto, o dicionário de dados gerado, as medições das lições
exports/               o esquema estrela do tamanho small em CSV
scripts/               measure_explain_lab.py
src/                   a ferramenta de linha de comando, em Python
tests/                 a suíte pytest e seus arquivos de referência
docker-compose.yml     PostgreSQL 16 para uso local
pyproject.toml         empacotamento e configurações do ruff, do mypy e do pytest
README.md              a versão em inglês
README.pt-BR.md        este arquivo
LICENSE                MIT
```

## Limites

* Os dados são sintéticos e os efeitos neles são plantados. Nada aqui é resultado.
* Tempos dependem da máquina, e os formatos de plano só foram conferidos no PostgreSQL 16.
* O executor de migrações é uma ferramenta didática. Num projeto de verdade use Flyway, sqitch ou Alembic.
* Não há segurança por linha (row-level security) nem autenticação além dos dois papéis: nada aqui é multi-inquilino.
* É desenvolvido e testado no Linux. O código lê arquivos como UTF-8, normaliza quebras de linha e usa `pathlib`, então
  deve se comportar igual no Windows, mas o CI não roda lá.
* O [`docs/design-notes.md`](docs/design-notes.md) termina com o que mudaria em escala real (particionar `trial_feature`,
  um índice BRIN, uma réplica para os dashboards). Nada disso está implementado.

## Licença

MIT, veja [`LICENSE`](LICENSE).
