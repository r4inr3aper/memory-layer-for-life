# Phase 1 report: memory ingestion pipeline

**Project:** Second Brain backend. **Report date:** 12 October 2026.

**Status:** Phase 1 is built and verified by automated tests. Live model quality was measured in twelve evaluation runs. The best score is 122 of 124 cases. Work on quality stopped when the API credit ran out.

This report covers all of Phase 1: what was built, every test that was run and what it returned, how Claude Haiku 5.5 and Claude Sonnet 5.5 performed, what failed, what was improved, what was fixed, and what is still open.

**Privacy.** The golden dataset is built from private notes and is kept out of version control. This report therefore names cases by id (for example `task_002`) and describes them in general terms. It never quotes a note. To read a case in full, open it in the console under Evaluations, where it is read from your own database.

**Times.** All times are UTC. The clock of the laptop is 5 hours 30 minutes ahead, so the evaluation runs of the evening of 11 October (UTC) happened after midnight on 12 October local time.

## 1. The short version

| Question | Answer |
|---|---|
| Is the pipeline built? | Yes. A note goes in, is read by a model, and comes out as proposed memories that each point back to the exact words they came from. Retries, replay, and protection against duplicates are enforced by the database. |
| Do the automated tests pass? | Yes. There are 887 tests in four suites. The last full run gave 886 passed and 1 skipped. The skipped test only needed this report file to exist, and it passes now that the file is here. Coverage is 99 percent. The linter and the strict type checker report nothing. |
| Best live score, Sonnet 5.5 | 122 of 124 cases (98.4 percent), reached in two runs in a row. |
| Best live score, Haiku 5.5 | 120 of 124 cases (96.8 percent). |
| Was 124 of 124 reached? | No. |
| How many model calls were made? | 2,608. Of these, 2,599 belong to the twelve evaluation runs and 9 were connection checks and small trials. The provider rejected 51 of them: 48 for lack of credit during the last run, 2 in a probe that confirmed the credit was gone, and 1 sent on purpose with a wrong key. |
| What did it cost? | About 5.39 US dollars: 0.62 on Haiku and 4.77 on Sonnet. |
| Is Haiku good enough to use? | Yes, for everyday capture. It costs about a tenth of Sonnet. Its weak spot: in 1 to 3 notes out of about 116 it states a guess as if it were certain. |
| Why did the work on quality stop? | The Anthropic credit ran out at about 19:30 UTC on 11 October, in the middle of run 12. No live call has been possible since. |

Five things to remember:

1. **The system only proposes.** Every memory the pipeline writes has the status `proposed` and carries the quote it is based on. Nothing is activated, merged, or overwritten automatically.
2. **Scores rose through general rules, never through answers to the test.** The extraction prompt contains no dataset case, and no label was edited. Haiku went from 97 to 120 through three rounds of general prompt rules, one fix to the scoring, and one piece of arithmetic moved from the model into code.
3. **One case fails every time.** `task_002` failed in all 11 runs that scored it. It is a disagreement between the label and what the note actually says, and it was left alone on purpose.
4. **The final configuration has one complete measurement.** The final prompt and judge were scored by exactly one complete run (122 of 124). The second was cut short by the credit running out.
5. **Every model call is now logged.** A table records each call with its tokens, cost, duration, and result, and a web console shows it. The 2,608 calls of Phase 1 were made before that table existed, so they appear as totals per run and not one by one.

## 2. What Phase 1 had to deliver, and what was built

The roadmap defines Phase 1 as: source message, then extraction, then entity resolution, then structured memory, then persistence, with replay and idempotency. Idempotency means that doing the same thing twice has the same effect as doing it once.

### 2.1 Roadmap deliverables

| Deliverable | What exists now |
|---|---|
| Raw message intake | `POST /api/v1/ingestion/units` and `POST /api/v1/ingestion/batches`. The caller sends a *unit*: 1 to 20 messages that are read together, in order, as one thought. A batch holds up to 100 units and is stored completely or not at all. A database trigger rejects every change to a stored raw message. |
| Versioned extraction contract | `app/schemas/extraction.py`, contract 1.0. The model returns a disposition (`extract`, `context`, or `abstain`), memories, and entity mentions. Each memory has a type, a statement, a state, a confidence, evidence quotes with message numbers, a note on what is unclear, and optional time and money details. The model is never asked for ids, timestamps, or character positions. The system computes those. |
| Provider-independent extraction | The pipeline depends on an `Extractor` interface. `AnthropicExtractor` is the only adapter and the only place that talks to the Anthropic SDK. |
| Entity resolution | Exact and deterministic. A name matches an entity only on equal type and equal normalised name. One candidate resolves the mention, several leave it `ambiguous`, none creates a new entity, and text that cannot be a name stays `unresolved`. |
| Memory construction and provenance | 16 memory types. Every memory is linked to every message it rests on. A quote is stored as evidence only if it really occurs in the message it cites. |
| Processing runs and errors | A run moves from `queued` to `running` and ends as `succeeded`, `needs_review`, or `failed`. Every attempt is kept in an append-only event table. A failure is stored as an error code with a short description, and a test checks that the detail of a run never contains the text of a note. |
| Idempotency and concurrency | Three identities, each a unique constraint in the database: the source message, the processing run (a hash of the pipeline version and the ordered message ids), and the output. Workers claim runs atomically, and a worker that lost its claim cannot write. |
| Replay | `POST /api/v1/processing/replays`, for single runs, for every unit that contains a given message, or for everything up to a limit. |
| Retry and recovery | Transient failures are retried with exponential backoff, up to 3 attempts. A run abandoned by its worker is released after 600 seconds. `python -m scripts.process_pending` is the recovery worker. |
| Regression tests | 887 automated tests, including all 124 golden cases run through the real pipeline on PostgreSQL. |

### 2.2 Exit gates

The roadmap says a phase is complete only when its behaviour is verified. Each gate is listed with the tests that prove it. The names are test names in `tests/integration`.

| Exit gate | Evidence |
|---|---|
| Reprocessing the same version creates no duplicates | `replaying_the_same_version_has_no_effect`, `redelivering_a_message_creates_nothing_new`, `concurrent_deliveries_of_one_message_store_it_once`, `concurrent_workers_execute_a_run_exactly_once`. In the live smoke test, replaying two processed units returned `unchanged` for both. |
| Reprocessing with a new version preserves history | `a_new_version_gets_a_new_run_and_keeps_history`, `replaying_a_new_version_twice_creates_one_run`. |
| Every memory can be traced to evidence | `run_stores_a_proposed_memory_with_its_evidence`, `every_message_of_a_unit_is_linked_to_the_memory`, `a_quote_that_is_not_in_the_message_is_not_stored_as_evidence`. |
| Failed processing never loses raw input | `raw_messages_cannot_be_updated`, `a_message_with_a_run_cannot_be_deleted`, `invalid_extractor_output_goes_to_review_and_stores_nothing`, `failure_after_extraction_reuses_the_stored_result_on_retry`. |
| Ambiguity is represented, not guessed | `two_candidates_leave_the_mention_ambiguous`, `text_that_cannot_be_a_name_stays_unresolved`, `abstention_sends_the_run_to_review_without_memories`. Every memory also has its own field for what is unclear. |

### 2.3 Built in addition to the roadmap

- **A log of every model call** (table `llm_calls`), with tokens, estimated cost, duration, and result. See section 14.
- **Stored evaluations.** Runs and the result of every case are kept in the database, so runs can be compared.
- **A test console**, a web page with seven screens: overview, single test call, evaluations, the detail of one evaluation, model calls, pipeline, and the Phase 1 results.
- **Arithmetic in code.** When a note writes out a sum, the total is recomputed by the application and never trusted from the model.
- **Billing failures are recognised.** An account without credit gives a clear error, and an evaluation hit by it marks the affected cases as not evaluated.
- **A refusal fallback**, requested only from models that support it.
- **A catalog of models and list prices**, the single source for every cost figure.

### 2.4 Deliberately not built

These were decided against for Phase 1 and are recorded as ADR-022:

- A WhatsApp export parser with automatic grouping of messages. The export file itself was not available, only the dataset made from it.
- Authentication. The API is for a trusted local environment only.
- Embeddings, search, deduplication, supersession, and review actions. These belong to Phases 2 and 3.

### 2.5 Size of the work

| Measure | Count |
|---|---|
| Database migrations | 3 |
| Database tables | 15 |
| API operations | 28 |
| Python source files under the type checker | 118 |
| Python statements measured by coverage | 4,844 |
| Automated backend tests | 887 |
| Console source files | 54 |
| Decisions recorded during Phase 1 | ADR-010 to ADR-025, in `context for agent/DECISIONS.md` |

## 3. How quality was measured

### 3.1 Three layers

Quality is checked in three layers, from the cheapest to the most expensive (ADR-021):

1. **Deterministic tests.** They never call a model. They check the rules of the system: what counts as a duplicate, how a run moves between states, how names are matched, what the database refuses.
2. **The golden cases through the real pipeline.** All 124 cases run through the real code on PostgreSQL with a stand-in extractor that answers what the dataset expects. This proves that a correct answer from a model is stored correctly.
3. **Live evaluation.** A real model reads each case and every answer is scored. This is the only layer that costs money, and the only one that measures the model.

### 3.2 The golden dataset

The dataset is the file `golden.jsonl`: 124 cases made from real notes-to-self.

| Property | Value |
|---|---|
| Cases | 124 |
| Expected outcome | 101 `extract`, 15 `context`, 8 `abstain` |
| Expected memories | 116 cases expect one memory, 8 expect none |
| Messages per case | 105 cases have one message, 13 have two, 5 have three, 1 has four |
| Distinct source messages | 148 |
| Distinct units | 123. Two cases share one unit and expect different parts of it. |
| Forbidden behaviours (`must_not` rules) | 156 in total: 92 cases have one rule, 32 have two |
| Review status | All 124 are `draft_needs_human_review`, annotation version v0.1 |
| Type labels | 40 different free-text labels |
| Status labels | 7 different free-text labels |
| Entity labels | None |

Cases by the kind named in their id:

| Kind | Cases |
|---|---|
| task | 51 |
| idea | 26 |
| expense | 14 |
| abstain | 7 |
| resource | 4 |
| context, goal | 3 each |
| tech_note, question, reflection | 2 each |
| intent, workflow, schedule, ambiguous, quote, tech_bug, plan, bug, product_note, context_trip | 1 each |

Three facts about this dataset shape everything that follows:

- **It is a draft.** No case has been reviewed by a person. A score is a comparison with one annotator's first reading, not with the truth.
- **Its labels are free text.** The file `evaluation/label_mapping.py` says which of the 16 memory types is an acceptable reading of each label. It works per label and never per case, because a rule for one case would be editing the expected answer under another name.
- **It has no entity labels.** The dataset cannot say whether a person or a project was recognised correctly. Entity resolution is tested by the deterministic tests only.

### 3.3 The eight checks that decide a case

A case passes when every one of these checks passes.

| Check | Question it answers | Decided by |
|---|---|---|
| `valid_output` | Did the model return output that satisfies the contract and points only at messages that exist? | Code |
| `abstention` | Did the system abstain exactly when the case expects it? | Code |
| `coverage` | Do the produced memories convey the expected memory? Exact wording and an exact number of memories are not required. | Judge model |
| `memory_type` | Does the memory that corresponds to the expected one have a type the label mapping accepts? | Code, on the memory the judge names as the corresponding one |
| `no_invented_completion` | Is nothing marked as done unless the label says it already happened? | Code |
| `structured_fields` | Do amounts, currency, and dates agree with the label wherever the label states them? | Code |
| `must_not` | Is no forbidden behaviour of the case present? | Judge model |
| `grounded` | Does no memory state a fact the source does not support? | Judge model |

The first two checks are scored for every case. The other six are scored only for cases where a memory was expected and the model did not abstain. That is 110 to 116 cases depending on the run, which is why the tables below show totals such as 115 of 116.

### 3.4 Two comparisons that are reported but do not count

| Comparison | Why it does not decide a case |
|---|---|
| `extract` against `context` | The dataset is not consistent here. Notes of the same shape, such as a bare amount followed by an item name, carry different labels. |
| Pending or done state | Reported so the labels can be reviewed. The check `no_invented_completion` already covers the dangerous direction. |

### 3.5 The judge

Three of the checks need reading comprehension, so a model decides them. The judge receives the source messages, the memories the system produced, the annotator's reference memory, and the `must_not` rules. It returns a coverage verdict, the produced memory that corresponds most directly to the reference, one verdict per rule, and a list of unsupported claims. Each comes with an explanation that is kept for audit.

Three things to know about the judge:

- In every run the judge was the same model as the extractor: Haiku judged Haiku, and Sonnet judged Sonnet. The judge ran at effort `high`.
- The judge is itself a model and can be wrong. Section 11.5 lists the judging flaws that were found and corrected, and section 12 lists one that is still open.
- Everything that can be compared exactly (amounts, currencies, types, states) is checked by code and never left to the judge.

### 3.6 Rules we held ourselves to

- The extraction prompt never contains a dataset case. Its examples are invented.
- No label and no expected answer was edited.
- No prompt rule was written for a single case. Every rule added to the prompt is a general statement about notes.
- Every failure was put into one of three groups before anything was changed: a real weakness of the model, a flaw in the scoring or the judge, or a disagreement with a label. Only the first two were acted on.
- When a case failed because of a label dispute, it was left failing.

### 3.7 How to read a score

"122 of 124" means that in 122 cases all eight checks passed. It does not mean the system is right about 98.4 percent of all notes. It means it agrees with these draft labels, under these criteria, in 98.4 percent of these cases. Two runs with the same settings differ by about one case, because both the extractor and the judge are models (section 5.5).

## 4. Automated tests

These tests never call a model and cost nothing to run.

### 4.1 Final state

| Suite | Tests | Needs a database | What it checks |
|---|---|---|---|
| Unit | 373 | No | Domain rules, text normalisation, identities, the run state machine, arithmetic, the Anthropic adapter, the refusal fallback, the call observer, the price catalog, scoring, request logging, error mapping, settings |
| Contract | 16 | No | The published API description and the extraction output schema |
| Golden | 140 | No | The dataset loads, matches its schema, and every label has a mapping |
| Integration | 358 | Yes, local PostgreSQL | Migrations, schema drift, database constraints, ingestion, the pipeline runner, entity resolution, replay, recorded corrections, all golden cases through the real pipeline, the call log, test calls, evaluations, the console API |
| **Total** | **887** | | |

Result of the last full run, on 12 October: **886 passed, 1 skipped.** The skipped test is `test_the_phase_1_report_is_served`, which skips when this report file does not exist. It was run on its own after this file was written, and it passed.

| Check | Result |
|---|---|
| Linter (`ruff check`) | No findings |
| Type checker (`mypy`, strict settings) | No findings in 118 source files |
| Coverage | 99 percent: 4,844 statements, 22 not covered |

Integration tests always use the local database `second_brain_test`. The test setup replaces the database address before any application code is loaded, so tests cannot reach the hosted application database even when `.env` points at it.

### 4.2 How the suite grew

| When (UTC) | State of the tests |
|---|---|
| 11 Oct, 16:58 | Phase 0 as found: 47 unit tests and 8 contract tests passed. The integration tests could not start (2 errors while loading, `MultipleEventLoopsRequestedError`). The linter reported 79 errors and the type checker 44 errors in 18 files. |
| 11 Oct, 18:40 | 672 passed in 87.57 seconds. Linter and type checker clean (86 files). |
| 11 Oct, 18:50 | 700 passed. Coverage 99 percent (2,707 statements, 1 not covered). |
| 11 Oct, 19:26 | 753 passed in 88.70 seconds. |
| 11 Oct, 19:41 | End of the pipeline work: 761 passed in 113.63 seconds. 2,890 statements, 1 not covered. Type checker clean (88 files). |
| 12 Oct | After the call log and console work: 886 passed, 1 skipped. 4,844 statements, 22 not covered. Type checker clean (118 files). |

### 4.3 Tests worth knowing about

- **Schema drift test.** It builds the tables from the Python models in a scratch schema and compares columns, defaults, constraints, and indexes with the schema the migrations produce. Any difference fails the suite. Phase 0 had such differences and no test could see them.
- **Real migrations in tests.** The integration database is built by running the real migrations, not by creating tables from the models.
- **A race test that was itself tested.** One test starts concurrent runs that all meet the same new name and checks that only one entity is created. To prove the test can fail, the lock that prevents the race was removed: the test failed 3 times out of 3. With the lock restored it passed 3 times out of 3.
- **All golden cases through the real pipeline.** 125 tests run every case through capture, extraction with the stand-in extractor, entity resolution, and storage.
- **A privacy test that caught a real mistake.** A test requires that the detail of a processing run contains no text of a note. During the console work a change added message text to that response. The test failed, and the change was undone instead of weakening the test.
- **Call log tests.** Exactly one row per call, including calls that fail, calls whose answer cannot be used, and calls that are cancelled.

### 4.4 Checks on the console

| Check | Result |
|---|---|
| TypeScript type check | 0 errors |
| ESLint, with warnings treated as failures | 0 findings |
| Unit tests (formatting, routing, evaluation helpers) | 17 passed |
| Production build | Succeeds: 1.47 MB of JavaScript, 71 KB of styles |

These four were run with stand-in tools, because part of the normal toolchain is damaged on this laptop. Section 12.3 explains.

### 4.5 Checks done by hand

- Every console screen was opened in a headless browser and its screenshot was looked at.
- Every console endpoint was called on the running server against the hosted database.
- The single test call, the capture through the pipeline, and the failure of an account without credit were exercised end to end with a scripted stand-in for the model (section 14.6).

## 5. Live evaluation: all twelve runs

### 5.1 Settings common to every run

- All runs happened on 11 October 2026 between 18:51 and 19:30 UTC.
- Each run sends every case to the model once to extract. Every case that expected a memory, and for which the model produced one, is sent once more to be judged.
- The judge was the same model as the extractor, at effort `high`.
- Extraction ran at effort `medium`, except in run 6.
- Eight cases were processed at a time (three in the trial run).
- The request timeout was 30 seconds for the Haiku runs and 120 seconds from run 7 on.
- The evidence for each run is a folder `eval_reports/<timestamp>/` with `report.json` and `report.md`. All twelve were also imported into the database and can be opened in the console.

### 5.2 Scoreboard

| Run | Finished | Model | Effort | Passed | Failed | Not evaluated | Cost |
|---|---|---|---|---|---|---|---|
| 1 | 18:53 | Haiku 5.5 | medium | 97 | 27 | 0 | $0.092 |
| 2 | 18:59 | Haiku 5.5 | medium | 116 | 8 | 0 | $0.096 |
| 3 | 19:03 | Haiku 5.5 | medium | 118 | 6 | 0 | $0.102 |
| 4 | 19:09 | Haiku 5.5 | medium | **120** | 4 | 0 | $0.103 |
| 5 | 19:11 | Haiku 5.5 | medium | 119 | 5 | 0 | $0.104 |
| 6 | 19:14 | Haiku 5.5 | high | 119 | 5 | 0 | $0.123 |
| 7 | 19:17 | Sonnet 5.5 | medium | 3 of 3 | 0 | 0 | $0.074 |
| 8 | 19:19 | Sonnet 5.5 | medium | 121 | 3 | 0 | $0.906 |
| 9 | 19:21 | Sonnet 5.5 | medium | 120 | 4 | 0 | $1.053 |
| 10 | 19:26 | Sonnet 5.5 | medium | **122** | 2 | 0 | $1.081 |
| 11 | 19:29 | Sonnet 5.5 | medium | **122** | 2 | 0 | $1.086 |
| 12 | 19:30 | Sonnet 5.5 | medium | 75 | 1 | 48 | $0.570 |

Run 7 was a trial with three cases. Run 12 was cut short when the credit ran out, so it is not a measurement of quality. The other ten runs are complete runs over all 124 cases.

### 5.3 Result of each check in each run

Each cell is "cases that passed the check" over "cases the check was scored for". "Fields" is the check `structured_fields` and "Rules" is the check `must_not`.

| Run | Valid output | Abstention | Coverage | Type | No invented completion | Fields | Rules | Grounded |
|---|---|---|---|---|---|---|---|---|
| 1 | 124/124 | 118/124 | 109/110 | 95/110 | 109/110 | 110/110 | 108/110 | 106/110 |
| 2 | 123/124 | 121/123 | 114/115 | 112/115 | 115/115 | 115/115 | 115/115 | 114/115 |
| 3 | 124/124 | 124/124 | 115/116 | 113/116 | 116/116 | 115/116 | 115/116 | 114/116 |
| 4 | 124/124 | 124/124 | 116/116 | 114/116 | 116/116 | 116/116 | 115/116 | 114/116 |
| 5 | 124/124 | 124/124 | 116/116 | 114/116 | 116/116 | 116/116 | 116/116 | 113/116 |
| 6 | 124/124 | 123/124 | 114/115 | 113/115 | 115/115 | 115/115 | 113/115 | 114/115 |
| 7 | 3/3 | 3/3 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| 8 | 124/124 | 123/124 | 115/115 | 113/115 | 115/115 | 115/115 | 115/115 | 115/115 |
| 9 | 124/124 | 124/124 | 116/116 | 114/116 | 116/116 | 116/116 | 115/116 | 115/116 |
| 10 | 124/124 | 124/124 | 116/116 | 115/116 | 116/116 | 116/116 | 116/116 | 115/116 |
| 11 | 124/124 | 124/124 | 115/116 | 115/116 | 116/116 | 116/116 | 115/116 | 116/116 |
| 12 | 76/76 | 76/76 | 75/75 | 74/75 | 75/75 | 75/75 | 75/75 | 75/75 |

The two comparisons that do not count:

| Run | Extract or context agrees | Pending or done agrees |
|---|---|---|
| 1 | 113/124 | 103/110 |
| 2 | 115/123 | 112/115 |
| 3 | 118/124 | 113/116 |
| 4 | 118/124 | 114/116 |
| 5 | 119/124 | 115/116 |
| 6 | 118/124 | 113/115 |
| 7 | 2/3 | 2/2 |
| 8 | 117/124 | 115/115 |
| 9 | 118/124 | 113/116 |
| 10 | 118/124 | 114/116 |
| 11 | 118/124 | 113/116 |
| 12 | 78/80 | 74/75 |

### 5.4 Run by run

For each run: what was changed before it, which cases failed and on which check, and what was learned.

#### Run 1. Haiku baseline: 97 of 124

Nothing had been tuned. This was the first prompt, the first judge, and the first scoring.

| Failed check | Cases |
|---|---|
| `memory_type` (15) | `intent_001`, `task_002`, `task_008`, `expense_004`, `task_009`, `task_011`, `idea_017`, `tech_note_002`, `goal_001`, `goal_002`, `goal_003`, `task_037`, `task_040`, `product_note_001`, `expense_014` |
| `abstention` (6) | `task_006`, `task_033`, `expense_010`, `task_043`, `task_051`, `context_002` |
| `grounded` (4) | `expense_002`, `expense_008`, `expense_009`, `expense_014` |
| `must_not` (2) | `expense_002`, `idea_015` |
| `coverage` (1) | `task_013` |
| `no_invented_completion` (1) | `task_019` |

`expense_002` and `expense_014` each failed two checks, so the table names 29 failures in 27 cases.

The 27 cases fell into three groups:

- **Real weaknesses of the model.** It abstained on very short notes, such as a two-word reminder with an abbreviation or a bare written sum. It turned an amount next to an item into a statement that money was spent. It read a name next to an amount as a statement about who paid. It restated a personal observation as a general fact. It marked one item as done without being told so.
- **A flaw in the scoring.** The type check looked at every memory that helped convey the expected one. When the model split a note into several memories, a secondary part with a different type failed the case. One case was split into eight memories and failed for this reason alone.
- **Disagreements with labels**, for example a note labelled as a task that reads as a plain note. These were not tuned toward.

#### Run 2. Haiku: 116 of 124

Changes before this run:

- **Prompt rewritten** with general rules: keep unclear shorthand exactly as written; write ideas, opinions, and observations as the person's own and never as facts about the world; do not abstain only because a note is short or uses an abbreviation; a numbered or bulleted list is one memory; a question and its situation are one memory; a leading word such as "idea:" is a hint and not a decision; a name next to an amount does not say who paid or who owes; do not write "spent", "paid", "bought", or "owes" unless the note does; mark something as done only when the note clearly reports completion. New invented examples were added.
- **Judge:** it now names the one produced memory that corresponds to the reference, and it was told that a counterparty or a list of amounts is not a claim about who paid.
- **Scoring:** the type check looks only at that one corresponding memory.
- **Label mapping:** two labels were widened, `technical_note` and `product_requirement`, because the notes under them are of several kinds.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Recorded as a note; the label says task. |
| `task_008` | `memory_type` | Recorded as a note; the label says task. |
| `idea_017` | `memory_type` | Recorded as an idea; the label says reflection. |
| `task_013` | `coverage` | Partly covered. The reference contains detail that is not in the messages. |
| `ambiguous_001` | `abstention` | Two memories were produced from a note that names nothing concrete. |
| `abstain_003` | `abstention` | A bare reference to a row number was kept as a context note. |
| `idea_019` | `grounded` | A garbled word was replaced by a different, real word. |
| `task_044` | `valid_output` | The answer pointed at an entity mention that did not exist. The pipeline rejected it, as designed. |

The new wording on abstention had over-corrected: the model now kept two fragments it should have dropped.

#### Run 3. Haiku: 118 of 124

Changes before this run: shorthand is kept in quotes and never replaced by a guess; abstention is defined as "gives nothing that can be understood on its own", with a bare line or page number named as an example; an action on a placeholder is still nothing concrete; a terse reminder is an open task, with a note when it could also be read as done; a statement about what the person does or is like is a reflection. The description of one schema field was tightened so that every reference to an entity must be a valid position. The judge was told that parts of the reference that cannot be derived from the messages are out of scope.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Note against task, again. |
| `idea_017` | `memory_type` | Idea against reflection, again. |
| `goal_001` | `memory_type` | A personal wish recorded as an idea. |
| `goal_003` | `must_not` | The judge read the state `planned` as a commitment. A judging flaw. |
| `task_038` | `grounded` | The memory added an action the note does not state. |
| `expense_010` | `coverage`, `structured_fields`, `grounded` | The model added four written amounts and got a total that was wrong by exactly 100. |

Abstention was now right in all 124 cases. The arithmetic error was the important finding: a model must not be trusted to add.

#### Run 4. Haiku: 120 of 124, the best Haiku result

Changes before this run:

- **Arithmetic moved into code.** A new parser in `app/domain/arithmetic.py` reads sums written with plus, minus, times, divide, and brackets. It parses them and never executes them as code. When a note states both a calculation and a total, the application recomputes the total and records the correction with the run. The evaluation applies the same step.
- **Prompt:** an idea is something that could be built, tried, or explored; a statement about the person's own wishes, habits, or feelings is not an idea; a terse reminder keeps its content as written and gains no action the note does not state.
- **Judge:** the state `planned` only says that the item appears in a list. It is not a commitment.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Note against task. |
| `goal_001` | `memory_type` | Recorded as an idea; the label is a long-term goal. |
| `task_019` | `grounded` | The memory said something "was" done, although its own note on what is unclear said this was not known. |
| `tech_note_002` | `must_not`, `grounded` | The memory said something was "in place", which asserts that it was implemented. |

A pattern became visible: the model writes the correct doubt in the field for what is unclear, and still commits to one reading in the content.

#### Run 5. Haiku: 119 of 124

Change before this run, prompt only: when the model notes that something is unclear, the content must not settle it. It must quote the unclear words instead of choosing a reading, and it must not write that something "was done", "is in place", or "exists" when that is not known. One invented example was added.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Note against task. |
| `task_030` | `memory_type` | Recorded as an idea; the label is a learning intention. |
| `task_028` | `grounded` | The memory said the instruction was addressed to an assistant. |
| `idea_019` | `grounded` | A garbled word was read as a different word, as in run 2. |
| `expense_014` | `grounded` | An amount without a label was given a spending category. |

The `must_not` check was perfect for the first time (116 of 116). The score did not rise, because three other cases now failed on unsupported statements.

#### Run 6. Haiku at high effort: 119 of 124

Change: extraction effort raised from `medium` to `high`. Nothing else.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `abstention` | This time the model abstained. |
| `idea_004` | `memory_type` | Recorded as a task; the label says idea. |
| `idea_009` | `memory_type` | Recorded as a note; the label says idea. |
| `expense_009` | `must_not`, `grounded` | Totals per person were presented as sums the note had written out. |
| `context_002` | `coverage`, `must_not` | Two identical notes with different dates were merged into one. |

More effort did not help. Output grew from 85,929 to 135,887 tokens (58 percent more), the run cost 19 percent more, and the score stayed at 119. Across runs 4, 5, and 6 Haiku moved between 119 and 120 with different cases failing each time. That is a plateau, and it triggered the switch to Sonnet that had been agreed for this situation.

#### Run 7. Sonnet trial: 3 of 3

Before paying for a full run, three cases were sent to Sonnet: `task_001`, `abstain_002`, and `task_044`. The purpose was to confirm that the new request form works, because the switch to Sonnet came with a refusal fallback that uses a different API call. All three passed.

The trial cost $0.074, which is high for three notes. The three calls started together with nothing in the prompt cache, so each one paid to write the fixed instructions into the cache (21,291 tokens written in total).

#### Run 8. First complete Sonnet run: 121 of 124

Nothing was changed after run 6 except the model and the fallback.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `abstention` | Abstained, because the only subject of the note is an unnamed "it". |
| `idea_004` | `memory_type` | Recorded as a task; the label says idea. |
| `task_039` | `memory_type` | A list of open questions recorded as a plan; the label says open loop. |

This was the first run with no broken rule (115 of 115) and no unsupported statement (115 of 115). All three misses were judgement calls about type or abstention, and two of them came from prompt rules that were worded too literally.

#### Run 9. Sonnet: 120 of 124

Changes before this run, prompt only: abstain when a note names nothing specific because everything specific is replaced by placeholders; a note that says something specific about an unnamed "it" is recorded, with the missing subject noted as unclear; a list takes its type from its items (plan, open loop, or note); a prompt to oneself to come up with an approach is an idea. Two invented examples were changed or added.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Now recorded, as a note; the label says task. |
| `task_011` | `memory_type` | Garbled shorthand kept word for word as a note; the label says task. |
| `idea_013` | `grounded` | The judge flagged "wants to" as unsupported for a note written as an instruction to oneself. A judging flaw. |
| `goal_003` | `must_not` | The judge applied a rule about not repeating earlier notes. One unit cannot see earlier notes, so it cannot break that rule. A judging flaw. |

The failing cases were different from run 8. Two of the four were mistakes of the judge, not of the extractor.

#### Run 10. Sonnet: 122 of 124, the best result

Changes before this run:

- **Judge:** a rule about behaviour across notes cannot be broken by a single unit; a note written as an instruction or an aspiration may be recorded as something the person "wants to" or "intends to" do.
- **Prompt:** a cryptic work fragment that reads as something to do or fix is a task with a note on what is unclear, not a plain note. One invented example was added.

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Note against task. |
| `context_trip_001` | `grounded` | The judge flagged the memory's own general description of what the messages are about. A judging flaw. |

#### Run 11. Sonnet, final configuration: 122 of 124

Changes before this run:

- **Prompt:** state what the note says, without remarks about the note itself.
- **Judge:** a general description of what the messages plainly are is not an unsupported fact.
- The version labels of the prompt and of the judge were set back from "2" to "1", because nothing had been released under "2".

| Case | Failed check | What happened |
|---|---|---|
| `task_002` | `memory_type` | Note against task. |
| `task_045` | `coverage`, `must_not` | The memory said the link between an amount and an item was not stated, while the reference pairs them. On the rule, the judge marked a violation although its own explanation says the rule was not broken. |

This is the configuration that is in the code today.

#### Run 12. Sonnet, cut short when the credit ran out

This run was meant to show that 122 is stable. Partway through, the provider began to reject calls with HTTP 400 and the message that the credit balance was too low.

| Outcome | Cases |
|---|---|
| Passed | 75 |
| Failed | 1 (`task_002`) |
| Not evaluated | 48: 44 extraction calls and 4 judge calls were rejected |

At the time, the tool printed "75 of 124" and counted the 48 unreachable cases as failures. That was wrong and was fixed afterwards (section 11.6). The 76 cases that were scored show the same picture as run 11, but the run is not a measurement of quality.

### 5.5 What the twelve runs show

- **The trend.** Haiku: 97, 116, 118, 120, 119, 119. Sonnet: 121, 120, 122, 122.
- **Most of the gain came early.** The first round of general rules and the scoring fix moved Haiku from 97 to 116. Everything after that was worth 2 to 6 cases.
- **There is a noise floor of about one case.** Runs with nearly the same settings fail different cases. Apart from `task_002`, no case failed in more than three of the ten complete runs.
- **Failures move around.** 40 of the 124 cases failed in at least one run, 27 of them in the very first run. The other 84 cases passed in every complete run.
- **Cases that failed more than once** in the ten complete runs: `task_002` (10 times); `idea_017`, `goal_001`, and `goal_003` (3 times each); `task_008`, `task_011`, `task_013`, `task_019`, `tech_note_002`, `expense_009`, `expense_010`, `expense_014`, `context_002`, `idea_004`, and `idea_019` (twice each).

## 6. Other live model calls

Besides the evaluation runs, nine calls were made. All were on 11 October.

| Time | What | Result | Calls |
|---|---|---|---|
| 17:05 | Connection check with Haiku | Success | 1 |
| 17:07 | Connection check with a wrong key, on purpose | Failed as it should: "Anthropic rejected the API key" | 1 rejected |
| 17:24 | Connection check after the application database moved to a hosted server | Success | 1 |
| 17:58 | Schema trial: two structured-output calls on Haiku with one invented note | Both returned output that satisfies the contract, in 7.6 and 3.9 seconds | 2 |
| 18:50 | End-to-end smoke test on the local development database with Haiku | See below | 2 |
| 19:31 | Billing probe: one tiny request per model, with retries switched off | Both rejected with HTTP 400, credit balance too low | 2 rejected |

The smoke test sent two short test units through the real pipeline, with the real model and a real database:

- Both runs were processed in 7.9 seconds. One ended as `succeeded` and one as `needs_review`.
- The first unit produced two proposed task memories with evidence quotes, a note that the month of a date was not stated, and one resolved person entity.
- The second unit was a meaningless fragment. The model abstained and the run went to review, as designed.
- Replaying both units returned `unchanged` twice. No duplicate was created.
- The first call wrote 5,933 tokens to the prompt cache and the second call read them back.
- The smoke data was removed afterwards.

No model call was made through the running API server. The single test call of the console was verified with a scripted stand-in for the model (section 14.6), because by then there was no credit.

## 7. Calls, tokens, and cost

### 7.1 Prices

All costs in this report are estimates from list prices, checked on 12 October 2026, in US dollars per million tokens.

| Model | Input | Output | Cache write | Cache read |
|---|---|---|---|---|
| Haiku 5.5 | 0.10 | 0.50 | 0.125 | 0.01 |
| Sonnet 5.5 | 2.00 | 10.00 | 2.50 | 0.10 |

The prices live in one place, `app/domain/model_catalog.py`. The invoice from the provider is the final word.

### 7.2 Calls

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| Evaluation runs | 6, all complete | 6: 4 complete, 1 trial, 1 cut short |
| Extraction calls | 744 | 623, of which 44 rejected |
| Judge calls | 688 | 544, of which 4 rejected |
| Calls in evaluation runs | 1,432 | 1,167 |
| Other calls | 6 answered, 2 rejected | 1 rejected |
| **All calls** | **1,440** | **1,168** |

In total 2,608 calls: 2,557 were answered and 51 were rejected.

### 7.3 Tokens and cost of the evaluation runs

| Role | Model | New input | Output | Read from cache | Written to cache | Cost |
|---|---|---|---|---|---|---|
| Extraction | Haiku | 110,485 | 539,907 | 4,820,100 | 221,456 | $0.357 |
| Judge | Haiku | 373,489 | 414,953 | 1,316,295 | 38,058 | $0.263 |
| Extraction | Sonnet | 85,913 | 185,757 | 4,035,656 | 197,955 | $2.928 |
| Judge | Sonnet | 283,473 | 109,600 | 1,138,437 | 26,544 | $1.843 |
| **Total** | | **853,360** | **1,250,217** | **11,310,488** | **484,013** | **$5.39** |

Per model: Haiku $0.62, Sonnet $4.77.

The prompt cache did most of the work. Of all prompt tokens, 89 percent were read from the cache, at a tenth (Haiku) or a twentieth (Sonnet) of the normal input price. The fixed part of an extraction call, the instructions and the output format, is about 7,100 tokens and is cached. Only about 150 tokens per note are new.

### 7.4 What one call and one run cost

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| A complete run: 124 notes extracted and judged | $0.10 (from $0.092 to $0.123) | $1.03 (from $0.906 to $1.086) |
| One extraction, prompt already in the cache | $0.0005 | $0.0051 |
| One judge call | $0.0004 | $0.0034 |
| One extraction with nothing in the cache | about $0.0013 | about $0.021 |
| Output tokens per extraction | 610 to 693 (1,096 at high effort) | 320 to 326 |

The row "nothing in the cache" matters for daily use. A cache entry lasts about five minutes after its last use. Notes that arrive one at a time, minutes or hours apart, each pay to write the cache again. The Haiku figure was measured in the smoke test and the Sonnet figure in the three-case trial.

### 7.5 What 5 dollars buys

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| Complete evaluation runs | about 48 | 4 to 5 |
| Notes extracted in bulk, cache warm | about 10,400 | about 980 |
| Notes captured one at a time, cache cold | about 3,800 | about 240 |

### 7.6 A correction to the cost

The first cost figure reported for these runs was $5.91. It was too high. The evaluation code had its own small price table, and that table charged Sonnet cache reads at a tenth of the input price where the list price is a twentieth. Because 89 percent of prompt tokens were cache reads, the error was large: the Sonnet total was overstated by about 11 percent. The fix was to move all prices into the single catalog and to delete the second table. The corrected total is $5.39. The Haiku figures were right all along.

## 8. Haiku 5.5: what it did well and where it fell short

Haiku ran six complete evaluations: 97, 116, 118, 120, 119, 119.

### 8.1 What it did well

- **It follows the output format.** 743 of 744 answers satisfied the contract. The one bad answer was rejected by the pipeline and nothing was stored.
- **It learns from general rules.** Three rounds of plain rules and one scoring fix took it from 97 to 120. No instruction for a single case was needed.
- **It abstains correctly once told how.** After the definition of abstention was sharpened, it was right in 124 of 124 cases in runs 3, 4, and 5.
- **It does not invent completion.** From run 2 on, it never marked something as done without being told so.
- **Its numbers are right once arithmetic is taken away from it.** After run 3 the check on amounts, currency, and dates was perfect.
- **It conveys the expected memory.** Coverage was 116 of 116 in runs 4 and 5.
- **It is cheap.** A complete run costs 10 cents. One extraction costs about a twentieth of a cent.

### 8.2 Where it fell short

- **Unsupported statements, in every run.** The `grounded` check failed for 1 to 3 cases in each of the five tuned runs: 114/115, 114/116, 114/116, 113/116, 114/115. The cases were different each time, so no single rule removes them.
- **It notes a doubt and then ignores it.** The typical failure: the field for what is unclear correctly says that something is not known, and the content states one reading anyway. Examples by kind: saying that something was done or is in place; replacing a garbled word with a real one; adding a spending category, a payer, an addressee, or an action that the note does not contain.
- **It cannot be trusted to add.** It summed four written amounts wrongly. This is now done by code.
- **One malformed answer** in 744, pointing at an entity mention that did not exist.
- **More thinking did not help.** High effort cost 19 percent more and scored the same.
- **It is wordy.** It writes about twice as many output tokens per note as Sonnet.
- **Its last word is not in.** Haiku was never run on the final prompt and the improved judge. Its real score on the current configuration is unknown and may be higher than 120.

## 9. Sonnet 5.5: what it did well and where it fell short

Sonnet ran four complete evaluations: 121, 120, 122, 122.

### 9.1 What it did well

- **It follows the output format.** All 579 answers it gave satisfied the contract.
- **It does not state what the note does not say.** In its first complete run it broke no rule and made no unsupported statement. Over the four complete runs the `must_not` check passed 461 of 463 times and the `grounded` check 461 of 463 times. All four misses were traced to the judge or to the reference, not to the extraction (runs 9, 10, and 11 in section 5.4).
- **It never invented completion and never got a number wrong.** Both checks were perfect in every run.
- **It abstains correctly.** 124 of 124 in three of four runs. The one miss was `task_002`.
- **It is concise.** About 320 output tokens per note, half of what Haiku writes.
- **It is steady.** Four runs within two cases of each other.

### 9.2 Where it fell short

- **Type on ambiguous notes.** Its real misses were choices between neighbouring types: task or idea (`idea_004`), plan or open loop (`task_039`), note or task (`task_011`). The type check passed 113/115, 114/116, 115/116, and 115/116.
- **`task_002`**, in every run.
- **Cost.** A complete run costs about $1.03, ten times Haiku.
- **Thin evidence for the final configuration.** One complete run.
- **The refusal fallback was never needed**, so it has not been seen working against a real refusal.

## 10. Haiku or Sonnet

### 10.1 Side by side

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| Complete runs | 6 | 4 |
| Best | 120 of 124 | 122 of 124 |
| Latest | 119 | 122 |
| Lowest | 97, before any tuning | 120 |
| On the same prompt (runs 5 and 6 against run 8) | 119 and 119 | 121 |
| Valid answers | 743 of 744 | 579 of 579 |
| Cases with an unsupported statement, per tuned run | 1 to 3 | 0 confirmed |
| Output tokens per note | about 650 | about 320 |
| Cost of a complete run | $0.10 | $1.03 |
| Measured on the final prompt and judge | No | Yes, once |

### 10.2 Two limits of this comparison

- **Each model judged itself.** Haiku output was judged by Haiku, and Sonnet output by Sonnet. The two columns were not scored by the same judge, so part of the difference may come from the judging.
- **The later improvements were measured on Sonnet only.** Runs 9 to 11 improved the prompt and the judge. Haiku never ran with them.

### 10.3 Recommendation

- **Haiku is usable for everyday capture.** It passes about 96 percent of these cases, its output is valid, and its typical mistake is visible: every memory keeps the quote it rests on and a note on what is unclear, and every memory is only proposed. A wrong reading can be seen and corrected later. It will not silently replace anything.
- **Sonnet is the better extractor**, and the safer choice when a wrong statement would be costly. It is the default in the code. Captured one note at a time, a note costs about 2 cents on Sonnet and about a tenth of a cent on Haiku, so the price difference matters for daily use.
- **Changing the model later is safe.** The model name is part of the pipeline version. Replaying notes with another model creates new proposed memories next to the old ones and changes nothing that exists.
- **Before settling:** run Haiku once on the final configuration. It costs about 10 cents and answers the open question.

## 11. What went wrong, and what was done about it

### 11.1 Defects inherited from Phase 0

All were fixed.

| Defect | Effect | Fix |
|---|---|---|
| Integration tests could not run | No database behaviour was tested. The tests also built tables from the models, not from the migrations. | Test setup corrected. Tests now run the real migrations against a database whose name must end in `_test`. |
| Models and migration disagreed | Several CHECK constraints differed between the code and the database. | Migration 002 aligns both. The schema drift test guards it. |
| Constraint names doubled | Constraints were created under names such as `ck_entities_ck_entities_...`. | Renamed in migration 002. |
| Redelivery overwrote evidence | A message sent again with new content replaced the stored one. | Redelivery with other content is refused. A trigger rejects every UPDATE on `raw_messages`. |
| Provenance could not span messages | A unique constraint allowed a memory only one source per extraction. | Constraint corrected in migration 002. |
| Entity mentions in units of several messages | A unique constraint was wrong for them. | An ordinal column now identifies a mention. |
| Two services could not be used | One raised a NameError on import. One used a status that did not exist. | The service layer was rewritten. |
| Non-standard id type | Generated ids did not compare equal to the same ids read back from the database. | A compatible UUID version 7 generator is used. |
| 79 linter errors and 44 type errors | The tools could not be used as a gate. | All fixed. Both tools are clean under strict settings. |

### 11.2 Defects found while building Phase 1

All were fixed.

- The query that selects the next unit failed with a correlation error. It now uses an explicit subquery.
- Invisible Unicode characters in the text normaliser had turned into literal characters in the source file. They are now built from their code points.
- Three bugs in tests: one conflict test mixed two sources, one read objects after a rollback, and one migration test passed parameters of unclear type.
- A contract test wrongly forbade a schema keyword that the SDK keeps. The test was corrected.
- Coverage under-reported asynchronous code. The coverage settings were corrected, which raised the measured figure from 98 to 99 percent with the same tests.
- Unused repository and dependency helpers were deleted.

### 11.3 Model behaviour improved by general prompt rules

| Weakness | First seen | Rule added | Result |
|---|---|---|---|
| Abstained on short or abbreviated notes | Run 1, 6 cases | Do not abstain only because a note is short or uses an abbreviation. Abstain when nothing can be understood on its own. | Abstention right in 124 of 124 from run 3 |
| Turned an amount into "spent" or "paid" | Run 1 | Do not use those words unless the note does. A name next to an amount does not say who paid. | `must_not` 115 of 115 in run 2 |
| Restated opinions as facts | Run 1 | Write ideas, opinions, and observations as the person's own. | No repeat |
| Marked things as done | Run 1 | Done only when the note clearly reports completion. | Perfect from run 2 |
| Replaced unclear shorthand with a guess | Runs 1 and 2 | Keep unclear words exactly as written, in quotes. | Reduced on Haiku, not removed |
| Added an action or a status the note lacks | Runs 3 and 4 | Keep a reminder as written. When something is unclear, the content must not settle it. | Reduced on Haiku, not removed |
| Called a personal wish an idea | Runs 3 and 4 | An idea is something to build, try, or explore. A wish is not an idea. | No repeat after run 4 |
| Abstained on a note about an unnamed "it" | Runs 6 and 8 | A note that says something specific about an unnamed thing is recorded, with the subject noted as unclear. | Recorded from run 9 |
| Typed a list by its form | Run 8 | A list takes its type from its items. | No repeat |
| Kept a cryptic work fragment as a plain note | Run 9 | A fragment that reads as something to do or fix is a task, with a note on what is unclear. | No repeat |
| Commented on the note instead of stating it | Run 10 | State what the note says, without remarks about the note itself. | No repeat in run 11 |

### 11.4 Model behaviour fixed in code

- **Arithmetic.** The model added four amounts and was wrong by 100. Totals of written sums are now recomputed by a small parser, and each correction is recorded with the run.
- **Malformed references.** One answer pointed at an entity mention that did not exist. The pipeline already rejected such output. The description of the field in the output format was tightened as well, and the problem did not come back in the 1,075 answers that followed.

### 11.5 Flaws in the scoring and in the judge

| Flaw | How it showed | Fix |
|---|---|---|
| The type check looked at every memory | In run 1, notes split into several memories failed because a secondary part had another type. | Only the memory that corresponds to the reference is type-checked. |
| The judge read structured fields as claims | A counterparty or a list of amounts was taken as a statement about who paid. | The judge was told what those fields do and do not claim. |
| The judge read `planned` as a commitment | `goal_003` in run 3. | `planned` only says the item appears in a list. |
| The judge demanded knowledge only the annotator had | `task_013`: the reference contains detail that is not in the messages. | Parts of the reference that cannot be derived from the messages are out of scope. |
| The judge applied rules about other notes | `goal_003` in run 9. | A rule about behaviour across notes cannot be broken by one unit. |
| The judge flagged faithful restatements | `idea_013` in run 9, `context_trip_001` in run 10. | "Wants to" for an instruction to oneself, and a general description of the messages, are not unsupported facts. |

### 11.6 Operational problems

- **The credit ran out in the middle of run 12.** The provider answered HTTP 400. At that time the tool counted the 48 unreachable cases as failed and stored an unhelpful error. Four things were changed. A billing failure is recognised and reported as `EXTRACTION_PROVIDER_BILLING` with a clear message. It is never retried. A case that could not be reached is recorded as "not evaluated", which neither passes nor fails. An incomplete run says so and ends with its own exit code.
- **The cost was overstated** by a wrong cache price for Sonnet. See section 7.6.
- **The laptop ran out of memory.** It has 7.4 GB of RAM and had about 0.7 GB free. Under that pressure Windows refused file writes with error 1450. This crashed the local PostgreSQL once during a test run. It recovered after a restart and no data was lost. The same condition interrupted an installation of the console's packages and left files damaged. Section 12.3 describes what that still costs.
- **A change leaked note text into an API response.** A privacy test caught it and the change was undone (section 4.3).
- **Four logging tests failed only when the whole suite ran.** An earlier test left the logging library configured with cached loggers. The affected tests now install a fresh logger.

### 11.7 The improvement in numbers

| Measure | At the start | At the end |
|---|---|---|
| Haiku, cases passed | 97 | 120 at best, 119 in the latest run |
| Sonnet, cases passed | 121 | 122 |
| Abstention right (Haiku) | 118 of 124 | 124 of 124 in three runs |
| Cases with an unsupported statement (Haiku) | 4 | 1 to 3 |
| Cases with an unsupported statement (Sonnet) | 0 | 0 confirmed |
| Automated tests that could run | 55 | 887 |
| Linter errors | 79 | 0 |
| Type errors | 44 | 0, under strict settings |
| Coverage | Not measured | 99 percent |

## 12. What could not be fixed, or was not reached

Nothing in this list is hidden behind a passing test. Each item says why it is open and what it needs.

### 12.1 Quality

| Open item | Why | What it needs |
|---|---|---|
| 124 of 124 was never reached | The best result is 122. The two misses of the final run are a label dispute and a judging flaw. | A reviewed dataset and a steadier judge, not more prompt rules. |
| `task_002` fails in every run | The label says task. The note reads as a remark about something unnamed. The model recorded it as an idea, then as a note, and twice abstained. | A decision by the owner of the dataset. The label was not edited and no rule was written for this one case. |
| The final configuration has one complete run | The second run was cut short. | Two more Sonnet runs, about $2.10. |
| Haiku was not measured on the final configuration | The credit ran out first. | One run, about $0.10. |
| The judge can contradict itself | In run 11 one verdict marked a rule as broken while its own explanation said it was not. | Asking for the explanation before the verdict in the output format. Planned, not tried. |
| Each model judged itself | Budget. | One Haiku run judged by Sonnet, about $0.45. The script supports it with `--judge-model`. |
| Haiku still states a guess as certain in 1 to 3 notes per run | Four rounds of rules reduced it and did not remove it. More effort did not help. | Review of proposed memories (Phase 3), or Sonnet. |
| The refusal fallback is unproven | No refusal happened in any of the 12 runs. It is covered only by tests with a simulated provider. Haiku has no fallback. | A real refusal. |
| The speed of single calls was not measured | The call log did not exist during the runs. | Nothing. Every call is timed from now on. |

### 12.2 Dataset

| Open item | Why |
|---|---|
| All 124 cases are unreviewed drafts | Any score is a comparison with one first reading. |
| `extract` against `context` cannot decide a case | The labels are not consistent. Six cases disagree in nearly every run (section 13). |
| Entity recognition is not measured | The dataset has no entity labels. |
| Several references contain knowledge that is not in the messages | For example what an unnamed "it" refers to. The judge now ignores such parts. |

### 12.3 Engineering

| Open item | Why | What it needs |
|---|---|---|
| The call log holds no real provider call yet | It was built after the credit ran out. It was verified with tests and with a scripted stand-in for the model. | Credit and a key. The first connection check will create the first row. |
| The 2,608 calls of Phase 1 are not in the log one by one | They were made before the table existed. | Nothing can recover them. Their totals per run were imported from the report files. |
| The test call and the start of an evaluation from the console were never run against a real model | No credit. | Credit and a key. |
| The console cannot be rebuilt on this laptop with its normal tools | An interrupted installation left package files damaged. 506 files in 11 packages were restored from the local package cache without any download. Ten packages were not in the cache and could not be checked or repaired. Because of them the build tool (Vite), the test runner (Vitest), and the type generator cannot run, the icon package has no type definitions, and two libraries, for routing and for charts, could not be used. | A clean `npm install` with enough free memory. It was not done because nothing was to be installed. |
| The console was built with stand-in tools | For the reason above. It was bundled with esbuild taken from the local package cache, its styles were compiled with the Tailwind compiler that is installed in the project, routing and charts were written by hand, and the API types were generated by a small script. | The same clean installation. The source code needs no change for the normal build. |
| The lock file of the console is incomplete | Most entries have no download address and no checksum. | The same clean installation rewrites it. |
| The Docker image was not rebuilt | The project is run without Docker here. The Dockerfile was updated for the console and never built. | A build on a machine with Docker. |
| The hosted database is far away | It is in the US East region, on PostgreSQL 18. Requests from here take 0.2 to 4 seconds. | Recreating it in a nearer region. |
| No authentication | Deferred by decision (ADR-022). | Must exist before the API can be reached by anyone else. |
| No WhatsApp import | The export file was not available. | The file, and a tested rule for grouping messages. |
| `DEFAULT_TIMEZONE` is not set in `.env` | The model is given the time of each note in UTC. A word like "tomorrow" in a note written between midnight and 05:30 local time resolves to the wrong day. The console also groups cost by UTC days. | One line in `.env`, for example `DEFAULT_TIMEZONE=Asia/Kolkata`. |
| No version history | The project folder is not a git repository. | `git init` and a first commit, when wanted. |

## 13. Findings about the dataset

These are for whoever reviews the labels. Nothing was changed in the dataset.

- **`task_002`.** Failed in all 11 runs that scored it. The label is a task, and its reference summary speaks of a system and a project that the note itself does not name. This is the clearest candidate for a label review.
- **Six stable disagreements on `extract` against `context`.** In each, the label says `context` and the model said `extract`.

| Case | Disagreed in | Why the model extracted |
|---|---|---|
| `tech_note_001` | 10 of 10 complete runs | It reads as a working note about the person's own project. |
| `task_042` | 10 of 10 | It names specific items. |
| `context_003` | 10 of 10 | A number with a word that suggests a labelled amount. |
| `context_002` | 10 of 10, once as an abstention | The same shape as `context_003`. |
| `task_044` | 9 of 10 | It reads as an idea for something that could be built. |
| `idea_017` | 7 of 10 | The note begins with the word "idea". |

- **The same shape, two labels.** `expense_002` and `context_003` are both an amount followed by an item. One is labelled `extract` and the other `context`. This is why that comparison cannot decide a case.
- **`task_011`.** Garbled shorthand labelled as a task. A cautious system keeps it word for word.
- **`task_013`.** The reference states things that are not in the messages.
- **`goal_003`.** One of its forbidden behaviours is about not repeating earlier notes, which a single unit cannot see.
- **`idea_017`.** Labelled as a reflection and as `context`, while the note itself begins with "idea".
- **Shared inputs.** `task_020` and `plan_002` use the same unit and expect different parts of it. `abstain_007` and `context_003` share a message.
- **Line breaks.** 18 messages store a line break as two characters, a backslash and the letter n. The loader decodes them.

## 14. The model call log and the test console

This part was built after the evaluation, on request: a log of every model call, and a web page to test the system and to see usage and output quality.

### 14.1 What is recorded for every call

One row in the table `llm_calls` per call to the provider.

| Group | Fields |
|---|---|
| What was asked | Provider, operation (`extraction`, `judge`, or `connection_check`), requested model, prompt version, effort, token limit, whether the refusal fallback was requested |
| Who asked | Origin (`pipeline`, `playground`, `evaluation`, or `other`) and a link to the processing run with its attempt number, to the evaluation run with its case id, or to the test call |
| What happened | Status (`succeeded` or `failed`), the model that answered, the stop reason, the provider's request id, the HTTP status, the provider's error type, an error code, an error message |
| What it used | New input tokens, output tokens, tokens read from the cache, tokens written to the cache |
| What it cost | Estimated cost in US dollars, to six decimal places |
| When and how long | Start time, and duration in milliseconds |

### 14.2 Guarantees

- **Exactly one row per call.** This holds when the call succeeds, when the provider fails, when the answer cannot be used, and when the call is cancelled.
- **The log survives a failed run.** Each row is written in its own transaction.
- **Never the content.** A row holds facts about a call. It never holds the prompt, the note, or the answer. What a call was about is found through the run it links to.
- **The cost is fixed when the row is written.** It is computed from the price catalog at that moment and never recomputed. It is empty when the price of a model is not known.
- **The database refuses inconsistent rows.** A failed call must have an error code, token counts cannot be negative, and a call made for a run must name that run.
- **Every HTTP request is logged too**, with a request id (returned in the `x-request-id` header), the method, the path, the status, and the duration. Query strings are never logged.

### 14.3 Stored evaluations

An evaluation run and the result of each of its cases are rows in `evaluation_runs` and `evaluation_case_results`, written while the run is in progress. One evaluation runs at a time. It can be cancelled. A run whose process disappears is marked as interrupted. A case the provider could not answer is "not evaluated". The twelve report files of Phase 1 were imported with `python -m scripts.import_eval_reports`, which can be run again without creating duplicates.

### 14.4 The console

The console is a web page served by the API itself at its root address. It has seven screens.

| Screen | What it shows or does |
|---|---|
| Overview | Estimated cost per day, usage by model, by origin, and by operation, failed calls, the latest evaluation, and what the pipeline holds. |
| Playground | One test call. Type a note, choose a model and an effort, and see the memories, the validated JSON, the raw answer of the model, and the logged call with tokens, cost, and duration. It also shows the output format. A switch sends the note through the real pipeline instead. |
| Evaluations | Every stored run, the cases that fail most often, and a form to start a new run on all cases or on a selection, with a cost estimate before anything is sent. |
| Evaluation detail | One run: the result of each check, and for each case the source messages, the expected memory, what the model produced, and the verdict of the judge with its explanations. |
| Model calls | The call log, with filters. |
| Pipeline | Captured notes, how their processing went, the memories that came out, and the evidence for each memory. A failed run can be replayed. |
| Phase 1 results | The scoreboard by model, every run, the latest result of each check, and this report. |

### 14.5 New API operations

The call log and the console added 19 operations to the 9 of the pipeline. Fifteen only read. Four act: `POST /api/v1/console/connection-check`, `POST /api/v1/playground/extractions`, `POST /api/v1/evaluations`, and `POST /api/v1/evaluations/{run_id}/cancel`. The full list is at `/docs` when the server runs.

### 14.6 How it was verified

- **Automated tests.** The call observer, the call log, test calls, evaluations, and the console API are covered by the suite of section 4.
- **Against the hosted database.** All migrations were applied, the twelve runs were imported ("Imported 12, already stored 0, unreadable 0"), and every console endpoint answered with status 200.
- **With a scripted model.** A temporary copy of the server ran with a stand-in that answers like the model and then fails like an account without credit. A test call succeeded and was logged with an estimated cost of $0.000403. A note sent through the pipeline produced one memory and one resolved entity. A third call failed with `EXTRACTION_PROVIDER_BILLING` and the clear message. The call log, the usage summary, and the pipeline counts all matched. The scripted data was removed afterwards.
- **By eye.** Every screen was opened in a headless browser and its screenshot was checked, with real data where it exists.

### 14.7 Limits of the console

- No real model call has gone through it yet (section 12.3).
- It has no login. It is for this laptop only.
- The stored results of the evaluation cases contain the text of the golden notes, so the database is as private as the dataset.
- It was built with stand-in tools (section 12.3). The result is the normal page. Only the way it was produced differs.

## 15. State on 12 October 2026

| Item | State |
|---|---|
| Hosted application database | At migration 003, the latest. Holds the 12 imported evaluation runs. No captured notes yet. |
| Local PostgreSQL | Used by the tests only. The development database on it is empty. |
| Server | Runs on this laptop on port 8000 and serves the API, the API documentation, and the console. |
| Model | `.env` selects Haiku 5.5. The default in the code is Sonnet 5.5. |
| API key | None in `.env`. The console says that no call can be made, and test calls are switched off. |
| Evidence of the runs | 12 folders in `eval_reports/`, each with `report.json` and `report.md`. They quote notes and are kept out of version control. |

## 16. Recommended next steps

In this order. Costs are estimates from section 7.

| Step | Cost | Why |
|---|---|---|
| 1. Add credit, put a key in `.env`, and press the connection check in the console | Under a cent | Creates the first real row in the call log and proves the whole chain. |
| 2. One Haiku run on the final configuration | About $0.10 | Answers how good Haiku really is today. |
| 3. Two more Sonnet runs | About $2.10 | Shows whether 122 is stable. |
| 4. One Haiku run judged by Sonnet | About $0.45 | Removes the doubt that each model judged itself. |
| 5. Change the judge format so the explanation comes before the verdict, and run once on Sonnet | About $1.05 | Addresses the verdict that contradicted itself. |
| 6. Review the dataset labels, starting with `task_002` and the six cases of section 13 | Time only | Turns the score into a comparison with reviewed labels, and lets `extract` against `context` count. |
| 7. A clean installation of the console's packages | Time only | Restores the normal build tool, test runner, and type generator. |
| 8. Set `DEFAULT_TIMEZONE` in `.env` | Time only | Correct days for words like "tomorrow". |
| 9. Phase 2: retrieval | Not estimated | The next phase of the roadmap. |

Steps 1 to 5 together cost about $3.70.

## Appendix: where the evidence is

| Evidence | Where |
|---|---|
| Every evaluation run, case by case | Console, Evaluations. Also `eval_reports/<timestamp>/report.json`. |
| Scores by model, and this report | Console, Phase 1 results |
| Tests | The folder `tests/`, run with `pytest` |
| How a case is scored | `evaluation/scoring.py` |
| How labels are read | `evaluation/label_mapping.py` |
| The extraction prompt | `app/integrations/extraction/prompt.py` |
| The judge prompt | `evaluation/judge.py` |
| Prices | `app/domain/model_catalog.py` |
| Decisions and their reasons | `context for agent/DECISIONS.md` |
| How to start everything | `RUN_LOCALLY.md` |
