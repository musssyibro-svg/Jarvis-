# Code map

Every module, what it is for, and what it exposes. Generated from the
AST — regenerate with `python tools/codemap.py` after adding or
removing a module.

This is the file to read FIRST. `JARVIS_FULL_SOURCE.txt` is the
complete source and is 1.4 MB; it answers a different question.

168 source files · 662 public symbols

Descriptions come from each module's own docstring. A module with no
description here has no docstring — in this project that is a gap, not
a style choice: CLAUDE.md says the reasoning lives in the docstring.

## `./`

**`RUNTIME_VALIDATION.py`** — run on the TARGET WINDOWS PC (not in any sandbox).
  <br>`run_cmd`, `main`
  <br>`RUNTIME_VALIDATION.py`

## `backend/`

**`main.py`** — Jarvis OS backend
  <br>`ChatIn`, `TaskIn`, `NoteIn`, `SettingIn`
  <br>`backend/main.py`

**`mcp_server.py`** — drive Jarvis from any MCP client.
  <br>`main`
  <br>`backend/mcp_server.py`

## `backend/adapters/`

> Glue between the chat surface and the agents.

**`__init__.py`**
  <br>`backend/adapters/__init__.py`

**`commander_adapter.py`** — V9 chat adapter (extracted per Hard Constraint 1).
  <br>`handle_chat`
  <br>`backend/adapters/commander_adapter.py`

## `backend/agents/`

> The things that act. One orchestrator owns the state machine; the rest are workers it drives.

**`__init__.py`**
  <br>`backend/agents/__init__.py`

**`base_agent.py`** — Base class for all Jarvis agents
  <br>`BaseAgent`
  <br>`backend/agents/base_agent.py`

**`browser_agent.py`** — persistent browser sessions, login-once, reuse forever.
  <br>`classify_browser_error`, `with_retry`, `check_url`, `navigate`, `current_page_text`, `reap`, `close_domain`, `status`, `BrowserAgent`
  <br>`backend/agents/browser_agent.py`

**`commander.py`** — CommanderAgent: the single entry point for ALL Jarvis actions.
  <br>`detect_intent`, `is_risky`, `normalize_goal`, `get_status`
  <br>`backend/agents/commander.py`

**`desktop_agent.py`** — Full desktop control: mouse, keyboard, window management, file ops.
  <br>`emergency_stop`, `clear_emergency_stop`, `is_estopped`, `move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `type_text`, `type_text_raw`, `hotkey`, `press`, `compose_and_type` _(+22 more)_
  <br>`backend/agents/desktop_agent.py`

**`executor_agent.py`** — V9 autonomy core (LOCKED spec).
  <br>`ExecutorAgent`
  <br>`backend/agents/executor_agent.py`

**`memory_agent.py`** — Enhanced learning memory (V5)
  <br>`MemoryAgent`
  <br>`backend/agents/memory_agent.py`

**`orchestrator.py`** — shared live-state bus (SSE feed) + approval queueing.
  <br>`backend/agents/orchestrator.py`

**`orchestrator_core.py`** — V9 central brain (LOCKED spec).
  <br>`AgentState`, `IllegalTransition`, `OrchestratorCore`, `get_core`
  <br>`backend/agents/orchestrator_core.py`

**`perception_agent.py`** — V9 Stage 2 structured perception.
  <br>`PerceptionAgent`
  <br>`backend/agents/perception_agent.py`

**`proposal_agent.py`** — ProposalAgent — generates proposals, applications, and reply drafts.
  <br>`ProposalAgent`
  <br>`backend/agents/proposal_agent.py`

**`registry.py`** — Agent Registry (V9 hooks only).
  <br>`AgentRegistry`, `load_custom_agents`, `register_core_agents`
  <br>`backend/agents/registry.py`

**`scheduler.py`** — AutoMode scheduling for Jarvis V8.5.
  <br>`start_schedule`, `stop_schedule`, `get_schedule_status`
  <br>`backend/agents/scheduler.py`

**`score_agent.py`** — ScoreAgent — scores and filters opportunities.
  <br>`ScoreAgent`
  <br>`backend/agents/score_agent.py`

**`scout_agent.py`** — ScoutAgent — discovers opportunities across all enabled platforms.
  <br>`ScoutAgent`
  <br>`backend/agents/scout_agent.py`

**`v9_models.py`** — V9 typed data models (LOCKED spec).
  <br>`backend/agents/v9_models.py`

**`vision_agent.py`** — Vision system: screenshot capture, OCR, screen analysis, element detection.
  <br>`screenshot`, `screenshot_region`, `tessdata_ready`, `ocr_screen`, `ocr_image`, `find_text_on_screen`, `analyze_screen`, `locate_text_coords`, `click_text`, `find_image_on_screen`, `get_status`
  <br>`backend/agents/vision_agent.py`

## `backend/agents/custom/`

**`__init__.py`**
  <br>`backend/agents/custom/__init__.py`

## `backend/core/`

> Cross-cutting primitives (the browser lock).

**`__init__.py`**
  <br>`backend/core/__init__.py`

**`browser_lock.py`** — single-owner browser access, via a HEARTBEAT LEASE.
  <br>`acquire`, `heartbeat`, `release`, `current_owner`, `browser_session`
  <br>`backend/core/browser_lock.py`

## `backend/models/`

> SQLite schema and connection handling.

**`__init__.py`**
  <br>`backend/models/__init__.py`

**`clickworker.py`**
  <br>`init_clickworker_tables`
  <br>`backend/models/clickworker.py`

**`db.py`** — Jarvis v3 unified SQLite schema
  <br>`conn`, `init_db`, `init_v5`
  <br>`backend/models/db.py`

**`fiverr.py`** — Fiverr gigs + messages table definitions.
  <br>`init_fiverr_tables`
  <br>`backend/models/fiverr.py`

**`hubstaff.py`** — Hubstaff Talent jobs + applications table definitions.
  <br>`init_hubstaff_tables`
  <br>`backend/models/hubstaff.py`

**`zuodao.py`**
  <br>`init_zuodao_tables`
  <br>`backend/models/zuodao.py`

## `backend/platforms/`

> One module per freelance site. Scraping lives here.

**`__init__.py`**
  <br>`backend/platforms/__init__.py`

**`base.py`** — Abstract base for all job platforms.
  <br>`BasePlatform`
  <br>`backend/platforms/base.py`

**`contra.py`** — Contra — independent work platform. Scrapes public opportunity listings.
  <br>`ContraPlatform`
  <br>`backend/platforms/contra.py`

**`hubstaff.py`** — Fixed Hubstaff Talent scraper
  <br>`HubstaffPlatform`
  <br>`backend/platforms/hubstaff.py`

**`peopleperhour.py`** — PeoplePerHour — scrapes public project listings.
  <br>`PeoplePerHourPlatform`
  <br>`backend/platforms/peopleperhour.py`

**`remoteco.py`** — Remote.co — scrapes job listings via requests + BeautifulSoup.
  <br>`RemoteCoPlatform`
  <br>`backend/platforms/remoteco.py`

**`remoteok.py`** — RemoteOK public JSON API
  <br>`RemoteOKPlatform`
  <br>`backend/platforms/remoteok.py`

**`wellfound.py`** — Wellfound (AngelList Talent) — scrapes public job listings.
  <br>`WellfoundPlatform`
  <br>`backend/platforms/wellfound.py`

**`weworkremotely.py`** — We Work Remotely RSS feeds
  <br>`WeWorkRemotelyPlatform`
  <br>`backend/platforms/weworkremotely.py`

## `backend/providers/`

> The ONLY place a vendor SDK is imported. Enforced by .semgrep/jarvis.yml.

**`__init__.py`**
  <br>`backend/providers/__init__.py`

**`base.py`** — what every AI provider must be able to do.
  <br>`Provider`
  <br>`backend/providers/base.py`

**`ollama_provider.py`** — the local models, behind the provider interface.
  <br>`OllamaProvider`
  <br>`backend/providers/ollama_provider.py`

**`openai_compatible.py`** — one provider for every cloud model worth using.
  <br>`OpenAICompatible`
  <br>`backend/providers/openai_compatible.py`

## `backend/routes/`

> HTTP surface. Thin — routes translate, they don't think.

**`__init__.py`**
  <br>`backend/routes/__init__.py`

**`agents.py`** — Agent API: Commander, Desktop, Vision, Planner, Memory
  <br>`CommandRequest`, `ActionRequest`, `PlanRequest`, `MemoryStoreRequest`, `OutcomeRequest`, `DesktopActionRequest`, `InstallAgentRequest`
  <br>`backend/routes/agents.py`

**`analytics.py`**
  <br>`backend/routes/analytics.py`

**`automation.py`** — Auto Mode + queue management
  <br>`AutoRequest`
  <br>`backend/routes/automation.py`

**`brain.py`** — API for the Jarvis Brain (personal knowledge base).
  <br>`IngestIn`
  <br>`backend/routes/brain.py`

**`clickworker.py`**
  <br>`CompleteIn`, `AIAssistIn`
  <br>`backend/routes/clickworker.py`

**`fiverr.py`** — Fiverr gig management + inbox monitoring + custom offers.
  <br>`GigIn`, `GigUpdate`, `OfferRequest`
  <br>`backend/routes/fiverr.py`

**`hubstaff.py`** — Hubstaff Talent job discovery + application tracking.
  <br>`ScrapeRequest`, `ApplicationIn`, `AppStatusUpdate`
  <br>`backend/routes/hubstaff.py`

**`messages.py`** — Freelancer inbox monitoring + reply drafts.
  <br>`ReplyRequest`
  <br>`backend/routes/messages.py`

**`mind.py`** — the Brain layer's read surface.
  <br>`RouteIn`
  <br>`backend/routes/mind.py`

**`orchestrator.py`** — Orchestrator API + SSE live feed endpoint.
  <br>`PipelineRequest`, `ScheduleRequest`
  <br>`backend/routes/orchestrator.py`

**`orchestrator_feed.py`** — SSE feed of orchestrator state.
  <br>`backend/routes/orchestrator_feed.py`

**`os_console.py`** — the operating console's data surface.
  <br>`backend/routes/os_console.py`

**`planner.py`** — Long-term project planner API.
  <br>`ProjectIn`, `StepIn`, `StepPatch`, `GoalIn`
  <br>`backend/routes/planner.py`

**`proposals.py`** — Full proposal lifecycle: generate → send → track → work → submit
  <br>`GenerateRequest`, `StatusUpdate`, `WorkUpdate`
  <br>`backend/routes/proposals.py`

**`pulse.py`** — read side of the proactive Pulse engine.
  <br>`backend/routes/pulse.py`

**`scraper.py`** — Job scanning endpoint. V8.5: aggregates MULTIPLE platforms via ScoutAgent
  <br>`ScrapeRequest`
  <br>`backend/routes/scraper.py`

**`sessions.py`** — Platform login sessions + credential vault API.
  <br>`CredentialIn`, `PlatformIn`
  <br>`backend/routes/sessions.py`

**`system.py`** — System Doctor: reliability diagnostics.
  <br>`backend/routes/system.py`

**`workflows.py`** — saved, replayable tasks ("teach once, run forever").
  <br>`TeachIn`, `PreviewIn`
  <br>`backend/routes/workflows.py`

**`zuodao.py`**
  <br>`SubmissionIn`, `AIAssistIn`
  <br>`backend/routes/zuodao.py`

## `backend/services/`

> The things that decide, remember and explain. No I/O with the user; called by agents and routes.

**`__init__.py`**
  <br>`backend/services/__init__.py`

**`ai_router.py`** — one door for every AI call in Jarvis.
  <br>`invalidate`, `route_for`, `chain_for`, `ask`, `ask_stream`, `status`
  <br>`backend/services/ai_router.py`

**`analytics_service.py`** — Unified analytics across ALL platforms
  <br>`get_analytics`
  <br>`backend/services/analytics_service.py`

**`app_resolver.py`** — find the real executable for an app name, and REMEMBER it.
  <br>`init_app_paths`, `get_cached`, `remember`, `forget`, `resolve`, `list_known`
  <br>`backend/services/app_resolver.py`

**`auth.py`** — the gate in front of a machine that can type on your keyboard.
  <br>`token`, `rotate`, `require_token`, `desktop_control_enabled`, `check_origin`, `origin_ok`, `is_control_path`, `is_open_path`, `token_ok`, `authorize`, `status`
  <br>`backend/services/auth.py`

**`bid_executor.py`** — Executes APPROVED automation_queue items.
  <br>`execute_queue_item`, `execute_all_approved`, `stop_executor`, `executor_status`
  <br>`backend/services/bid_executor.py`

**`brain_core.py`** — the coordinator that makes the parts feel like one mind.
  <br>`state`, `route`, `start`
  <br>`backend/services/brain_core.py`

**`brain_decision.py`** — the decision layer. It ADVISES; it never takes over.
  <br>`Action`, `decide`, `after_goal`, `explain`
  <br>`backend/services/brain_decision.py`

**`brain_service.py`** — Jarvis Brain: local personal knowledge base (RAG).
  <br>`init_brain`, `embeddings_available`, `ingest`, `search`, `context_for`, `profile_context`, `projects`, `list_documents`, `delete_document`, `learn_from_chat`, `status`
  <br>`backend/services/brain_service.py`

**`browser_monitor.py`** — Monitor Freelancer inbox using Browser Use / Playwright.
  <br>`fetch_inbox_messages`, `sync_inbox_to_db`
  <br>`backend/services/browser_monitor.py`

**`capability_registry.py`** — what Jarvis can DO, described as data.
  <br>`all_capabilities`, `list_dicts`, `best_for`, `describe`
  <br>`backend/services/capability_registry.py`

**`clickworker_service.py`** — Clickworker task discovery via public API + web scraping.
  <br>`fetch_public_tasks`, `estimate_earnings`, `ai_assist_task`
  <br>`backend/services/clickworker_service.py`

**`config.py`** — one place that answers "what is this setting?"
  <br>`invalidate`, `get`, `get_bool`, `get_int`, `get_float`, `set`, `is_secret`, `effective`
  <br>`backend/services/config.py`

**`control.py`** — the stop button for autonomous work.
  <br>`Cancelled`, `pause`, `resume`, `cancel`, `clear`, `run_scope`, `busy`, `clear_stale`, `checkpoint`, `is_paused`, `is_cancelled`, `status`, `explain`
  <br>`backend/services/control.py`

**`conversation.py`** — what the last turn was about.
  <br>`remember`, `recall`, `forget`, `is_repeat`, `resolve`, `prompt_block`, `status`
  <br>`backend/services/conversation.py`

**`custom_platforms.py`** — add ANY freelance site yourself.
  <br>`init_custom_platforms`, `add_platform`, `list_platforms`, `delete_platform`, `set_enabled`, `scan`
  <br>`backend/services/custom_platforms.py`

**`decompose.py`** — turn a sentence into an ordered plan.
  <br>`split_clauses`, `parse_clause`, `decompose`, `describe`, `preview`
  <br>`backend/services/decompose.py`

**`deepseek_service.py`** — Unified AI service — Ollama (DeepSeek-R1 + Qwen) with Anthropic fallback.
  <br>`call_model`, `generate_proposal`, `generate_reply_draft`, `auto_work_job`
  <br>`backend/services/deepseek_service.py`

**`diagnostics.py`** — full-system diagnosis + a downloadable runtime report.
  <br>`deep_check`, `build_report`
  <br>`backend/services/diagnostics.py`

**`environment.py`** — what machine am I actually running on?
  <br>`scan`, `summary`, `get`, `start`
  <br>`backend/services/environment.py`

**`event_bus.py`** — Jarvis's internal nervous system.
  <br>`subscribe`, `unsubscribe`, `publish`, `recent`
  <br>`backend/services/event_bus.py`

**`experience.py`** — why a step failed, and what Jarvis has learned about it.
  <br>`classify`, `record`, `launch_wait_for`, `needs_extra_attempt`, `reliability`, `confidence`, `summary`
  <br>`backend/services/experience.py`

**`fiverr_service.py`** — Fiverr inbox monitoring via Playwright + AI reply/offer generation.
  <br>`fetch_fiverr_inbox`, `sync_fiverr_inbox`, `generate_custom_offer`
  <br>`backend/services/fiverr_service.py`

**`freelancer_api.py`** — Freelancer.com integration.
  <br>`fetch_api_jobs`, `scrape_freelancer`
  <br>`backend/services/freelancer_api.py`

**`hubstaff_service.py`** — Hubstaff Talent job discovery via Playwright + HTTP fallback.
  <br>`scrape_hubstaff_jobs`, `generate_application`
  <br>`backend/services/hubstaff_service.py`

**`income_engine.py`** — the always-on freelance loop.
  <br>`get_config`, `status`, `start`, `stop`, `run_once_now`, `start_watchdog`
  <br>`backend/services/income_engine.py`

**`live_plan.py`** — the plan, visible while it runs.
  <br>`begin`, `ensure`, `step_start`, `step_end`, `finish`, `skip`, `retry`, `stop`, `should_skip`, `take_retry`, `snapshot`, `current_step`, `clear`
  <br>`backend/services/live_plan.py`

**`maintenance.py`** — keeps a 24/7 Jarvis from eating a 16GB machine alive.
  <br>`wal_checkpoint`, `prune_rows`, `prune_screenshots`, `vacuum`, `reap_browser`, `unload_idle_models`, `run_due`, `stats`, `start`
  <br>`backend/services/maintenance.py`

**`memory_pressure.py`** — the number that explains almost everything.
  <br>`loaded_models`, `hogs`, `level`, `status`, `free_now`
  <br>`backend/services/memory_pressure.py`

**`model_router.py`** — pick the best model that's actually installed AND fits in RAM.
  <br>`installed_models`, `free_ram_gb`, `pick`, `pick_model`, `keep_alive_for`, `unload`, `status`
  <br>`backend/services/model_router.py`

**`narrate.py`** — "why did that happen?", answered as a chain.
  <br>`why`, `as_text`
  <br>`backend/services/narrate.py`

**`ollama_manager.py`** — Jarvis V8
  <br>`fast_model`, `reasoning_model`, `vision_model`, `probe_reason`, `resolve_models`, `health`, `validate_model`, `fast`, `reason`, `vision`, `status`
  <br>`backend/services/ollama_manager.py`

**`os_state.py`** — ONE live snapshot of the whole system.
  <br>`snapshot`
  <br>`backend/services/os_state.py`

**`persona.py`** — what Jarvis knows about YOU, permanently.
  <br>`remember`, `forget`, `all_facts`, `get`, `sync_from_environment`, `prompt_block`, `style_hint`, `status`, `learn_from_text`, `start`
  <br>`backend/services/persona.py`

**`planner_service.py`** — Long-term project planner (Brain-linked).
  <br>`init_planner`, `decompose`, `create_project`, `add_step`, `set_step_status`, `delete_step`, `delete_project`, `get_project`, `list_projects`, `execute_project`, `maybe_complete`, `start_watchdog`, `is_executing`, `summary_line`
  <br>`backend/services/planner_service.py`

**`platform_health.py`** — per-site reliability: history, backoff, auto-pause.
  <br>`init_health`, `record`, `should_scan`, `resume`, `all_health`, `summary`
  <br>`backend/services/platform_health.py`

**`platform_meta.py`** — what KIND each platform is, and how you apply there.
  <br>`kind`, `submittable`, `needs_login`, `apply_note`
  <br>`backend/services/platform_meta.py`

**`profile_service.py`** — Persistent freelance profile.
  <br>`get_profile`, `save_profile`, `prompt_block`
  <br>`backend/services/profile_service.py`

**`providers.py`** — "what do I use for THIS, on THIS machine?"
  <br>`resolve`, `provider_for`, `invalidate`, `status`
  <br>`backend/services/providers.py`

**`pulse_service.py`** — Jarvis Pulse: the proactive layer.
  <br>`init_pulse`, `briefing`, `tick`, `start_pulse`, `recent`, `mark_seen`
  <br>`backend/services/pulse_service.py`

**`reflection.py`** — the loop that lets Jarvis get better, not just repeat.
  <br>`reflect`, `recent`
  <br>`backend/services/reflection.py`

**`selfeval.py`** — grade the run, then change something.
  <br>`score`, `adjustment`, `apply`, `evaluate`, `recent`, `summary`
  <br>`backend/services/selfeval.py`

**`session_manager.py`** — Per-platform login sessions (login once, reuse forever).
  <br>`list_platforms`, `check_status`, `is_logged_in`, `logged_in_platforms`, `open_login`, `start_reply_monitor`, `check_replies`
  <br>`backend/services/session_manager.py`

**`simulate.py`** — "what would you do?", answered without doing it.
  <br>`task`, `earning`, `as_text`, `match`
  <br>`backend/services/simulate.py`

**`teach.py`** — watch me do it once, then do it yourself.
  <br>`available`, `start`, `stop`, `distil`, `status`, `match`
  <br>`backend/services/teach.py`

**`tool_registry.py`** — deterministic action shortcuts.
  <br>`default_browser`, `search_url`, `split_query`, `resolve_steps`, `is_known_command`, `list_tools`
  <br>`backend/services/tool_registry.py`

**`trace.py`** — execution tracing. Every request records the EXACT path it took.
  <br>`start`, `step`, `record_cost`, `timed`, `profile`, `reset_costs`, `failure`, `failures`, `finish`, `current_id`, `recent`, `get`, `summary`
  <br>`backend/services/trace.py`

**`vault.py`** — Encrypted local credential vault.
  <br>`init_vault`, `vault_ready`, `store_credential`, `get_credential`, `list_credentials`, `delete_credential`
  <br>`backend/services/vault.py`

**`workflow_service.py`** — teach a task once, replay it by name forever.
  <br>`init_workflows`, `teach`, `get`, `run`, `list_workflows`, `delete`, `find_run_command`
  <br>`backend/services/workflow_service.py`

**`world_model.py`** — Jarvis's live picture of reality.
  <br>`snapshot`, `summary`, `get_cached`, `start`
  <br>`backend/services/world_model.py`

**`zuodao_service.py`** — Zuodao (做道) task discovery and tracking.
  <br>`fetch_tasks`, `ai_assist_task`
  <br>`backend/services/zuodao_service.py`

## `backend/tests/`

> Offline unit tests. Every case is a bug that reached the user once.

**`conftest.py`** — Shared pytest fixtures.
  <br>`pytest_configure`
  <br>`backend/tests/conftest.py`

**`test_app_detection.py`** — "It opened QQ the first time but never again."
  <br>`test_a_window_title_alone_is_not_evidence`, `test_already_running_actually_raises_the_window`, `test_unraisable_window_is_reported_not_hidden`
  <br>`backend/tests/test_app_detection.py`

**`test_click_verification.py`** — A click "succeeds" the moment pyautogui returns — which means the mouse moved,
  <br>`test_a_click_that_changes_nothing_is_not_verified`, `test_a_click_that_changes_the_screen_is_verified`, `test_a_click_that_opens_a_window_is_verified_even_if_pixels_match`, `test_no_eyes_is_reported_as_doubt_not_as_failure`, `test_an_observed_dead_click_does_fail_the_step`, `test_the_comparison_needs_a_real_difference`
  <br>`backend/tests/test_click_verification.py`

**`test_config_store.py`** — Settings must save on a database that has never been initialised.
  <br>`test_set_succeeds_on_an_uninitialised_database`, `test_the_value_is_actually_readable_afterwards`, `test_get_still_falls_back_when_nothing_is_stored`, `test_a_failed_write_reports_it_rather_than_pretending`
  <br>`backend/tests/test_config_store.py`

**`test_conftest_guard.py`** — Does the test harness itself still work?
  <br>`test_outbound_connections_are_blocked`, `test_loopback_is_still_allowed`
  <br>`backend/tests/test_conftest_guard.py`

**`test_control.py`** — Regression tests for the stop button.
  <br>`test_cancel_with_nothing_running_is_cleared`, `test_cancel_during_live_work_is_kept`, `test_run_scope_does_not_leak`, `test_run_scope_releases_on_exception`, `test_nested_scopes_count`, `test_checkpoint_raises_on_cancel`, `test_checkpoint_is_a_no_op_when_nothing_is_pending`, `test_pause_then_cancel_does_not_deadlock`, `test_resume_clears_pause`, `test_status_is_readable`
  <br>`backend/tests/test_control.py`

**`test_conversation.py`** — Follow-up messages used to be parsed in complete isolation.
  <br>`open_app_turn`, `test_close_it_means_the_app_we_just_opened`, `test_a_bare_instruction_inherits_the_current_app`, `test_the_inherited_app_does_not_end_up_in_the_TYPED_TEXT`, `test_an_explicit_app_is_never_overridden`, `test_do_it_again_repeats_the_last_command`, `test_repeating_a_follow_up_repeats_the_ACTION_not_the_pronoun`, `test_with_no_history_a_pronoun_stays_unresolved`, `test_do_it_again_with_nothing_to_repeat_says_so`, `test_context_expires`, `test_sessions_do_not_leak_into_each_other`, `test_a_full_sentence_is_left_alone`, `test_remembers_the_app_from_executor_RESULT_steps`, `test_the_app_carries_across_turns_that_dont_name_one` _(+2 more)_
  <br>`backend/tests/test_conversation.py`

**`test_decompose.py`** — Regression tests for command understanding.
  <br>`plan`, `actions`, `typed`, `test_notepad_question_is_answered_not_transcribed`, `test_question_to_a_chat_app_stays_literal`, `test_composed_prose_is_not_followed_by_enter`, `test_type_stays_literal`, `test_write_composes`, `test_comma_is_a_step_boundary`, `test_comma_inside_literal_text_is_not_a_boundary`, `test_and_inside_a_search_query_is_not_a_boundary`, `test_search_stops_at_a_follow_on_verb`, `test_three_clauses_stay_in_order`, `test_unhandled_clause_is_reported_not_dropped` _(+3 more)_
  <br>`backend/tests/test_decompose.py`

**`test_felt_behaviour.py`** — The three complaints that are actually about how Jarvis FEELS to use.
  <br>`test_a_busy_ollama_is_asked_once_not_once_per_poll`, `test_the_model_list_call_gives_up`, `test_busy_is_reported_differently_from_offline`, `test_a_qualifier_alone_is_still_a_name`, `test_an_unconfirmed_bid_is_not_recorded_as_sent`, `test_the_unconfirmed_branch_says_success_but_not_verified`, `test_a_look_at_an_unfocusable_app_fails_instead_of_answering`, `test_a_tray_app_is_not_reported_as_missing`, `test_a_failed_app_launch_gets_an_app_remedy_not_a_browser_one`, `test_chain_steps_carry_their_own_time_not_the_whole_run`
  <br>`backend/tests/test_felt_behaviour.py`

**`test_headless.py`** — Jarvis must survive a machine with no display.
  <br>`test_desktop_agent_imports_without_a_display`, `test_vision_agent_imports_without_a_display`, `test_input_refuses_with_a_reason_that_is_true`, `test_a_genuinely_missing_package_still_says_install_it`
  <br>`backend/tests/test_headless.py`

**`test_llm_budgets.py`** — Two ways a model call goes wrong on a 16 GB machine, and neither looks like a bug.
  <br>`test_every_kind_has_a_budget`, `test_every_kind_resolves_to_a_model_role`, `test_planning_is_cheaper_than_general_chat`, `test_the_planner_actually_asks_for_the_planner_budget`
  <br>`backend/tests/test_llm_budgets.py`

**`test_profiling_and_failures.py`** — "It didn't work" and "it feels slow" were both unanswerable.
  <br>`test_a_raising_action_records_the_traceback_not_just_the_message`, `test_an_unknown_action_is_not_recorded_as_a_crash`, `test_typed_text_is_reduced_to_its_length`, `test_ordinary_context_survives`, `test_the_buffer_is_bounded`, `test_the_profile_names_the_slowest_component`, `test_ranking_is_by_total_time_not_by_the_worst_single_call`, `test_a_call_that_throws_is_still_measured`, `test_every_chat_closes_its_trace`, `test_steps_carry_their_own_cost`
  <br>`backend/tests/test_profiling_and_failures.py`

**`test_security.py`** — Regression tests for the things that make Jarvis dangerous if they slip.
  <br>`test_dns_rebinding_host_is_refused`, `test_health_is_open_so_the_launcher_can_wait_for_it`, `test_anything_that_types_is_a_control_path`, `test_effective_settings_never_expose_a_key`, `test_a_masked_value_is_still_recognisable`, `test_demonstration_emits_a_placeholder_not_the_keystrokes`, `test_simulating_a_task_executes_nothing`
  <br>`backend/tests/test_security.py`

**`test_submission_confirmation.py`** — "I press approve all but I don't know if it sent it."
  <br>`FakePage`, `verdict`, `test_a_click_that_did_nothing_is_never_called_submitted`, `test_form_closing_and_navigating_counts_as_sent_without_words`, `test_refusal_wins_over_a_success_word_in_the_same_page`, `test_a_submission_is_never_retried`, `test_the_unchanged_verdict_reaches_the_user_as_a_failure`
  <br>`backend/tests/test_submission_confirmation.py`

**`test_url_gate.py`** — Where Jarvis is allowed to point a browser that is already signed in as you.
  <br>`test_a_doubly_prefixed_url_is_refused`, `test_localhost_with_a_port_is_refused_for_the_RIGHT_reason`, `test_chat_can_still_open_an_ordinary_site`, `test_a_refusal_says_why_and_is_not_retried`, `test_llm_parsed_actions_need_approval`, `test_screenshot_from_the_model_stays_cheap`
  <br>`backend/tests/test_url_gate.py`

## `frontend/`

**`vite.config.js`**
  <br>`frontend/vite.config.js`

## `frontend/src/`

> The React console. A CLIENT of the backend, never a place where logic lives.

**`App.jsx`** — entry point.
  <br>`App`
  <br>`frontend/src/App.jsx`

**`JarvisOS.jsx`** — the operating console.
  <br>`eventTime`, `JarvisOS`, `VitalsGraph`, `Console`, `Diagnostics`, `Metric`, `hhmm`
  <br>`frontend/src/JarvisOS.jsx`

**`colors.js`** — one safe way to build a translucent version of a colour.
  <br>`toRgb`, `tint`, `edge`, `btn`
  <br>`frontend/src/colors.js`

**`config.js`** — central API config (V8)
  <br>`apiFetch`, `apiPost`, `apiPatch`
  <br>`frontend/src/config.js`

**`main.jsx`**
  <br>`frontend/src/main.jsx`

**`theme.js`** — the one visual language, in a module that imports nothing.
  <br>`frontend/src/theme.js`

## `frontend/src/components/`

**`UI.jsx`** — shared micro-components
  <br>`Badge`, `StatCard`, `Ring`, `Modal`, `Btn`, `PageHeader`
  <br>`frontend/src/components/UI.jsx`

## `frontend/src/pages/`

> One file per screen.

**`Agents.jsx`**
  <br>`Dot`, `Agents`, `RegistryPanel`, `OutcomeForm`
  <br>`frontend/src/pages/Agents.jsx`

**`Chat.jsx`**
  <br>`Chat`
  <br>`frontend/src/pages/Chat.jsx`

**`Earn.jsx`** — freelance, fully autonomous.
  <br>`Earn`
  <br>`frontend/src/pages/Earn.jsx`

**`Logs.jsx`** — every decision, with a timestamp and a reason.
  <br>`chip`, `Logs`, `Empty`, `ms`, `Num`
  <br>`frontend/src/pages/Logs.jsx`

**`Memory.jsx`** — everything Jarvis knows, in one place you can edit.
  <br>`btn`, `Memory`
  <br>`frontend/src/pages/Memory.jsx`

**`Planner.jsx`** — watch Jarvis think, on the same screen as what it's doing.
  <br>`btn`, `secs`, `Simulation`, `Planner`
  <br>`frontend/src/pages/Planner.jsx`

**`Settings.jsx`** — the control centre.
  <br>`btn`, `Field`, `Settings`, `Fact`, `Row`
  <br>`frontend/src/pages/Settings.jsx`

## `tools/`

> Developer commands. Not shipped as part of the running system.

**`check_ui.mjs`** — tools/check_ui.mjs — does the UI actually put pixels on the screen?
  <br>`waitForServer`, `startVite`, `main`
  <br>`tools/check_ui.mjs`

**`codemap.py`**
  <br>`build`, `main`
  <br>`tools/codemap.py`

**`doctor.py`** — "why won't it start?", answered in ten seconds.
  <br>`add`, `check_layout`, `check_line_endings`, `check_python`, `check_node`, `check_ollama`, `check_playwright`, `check_tesseract`, `check_ports`, `main`
  <br>`tools/doctor.py`

**`dump_source.py`**
  <br>`collect`, `main`
  <br>`tools/dump_source.py`

**`failure_injection.py`** — Phase 0. Break Jarvis on purpose, in two minutes,
  <br>`Result`, `s_missing_app`, `s_clipboard`, `s_no_model`, `s_queue_load`, `s_browser_death`, `s_estop`, `s_learning`, `s_model_pressure`, `s_classification`, `s_control`, `s_decompose`, `s_plan_visibility`, `s_selfeval` _(+15 more)_
  <br>`tools/failure_injection.py`

**`setup.py`** — install everything Jarvis needs, then say what's left.
  <br>`say`, `step`, `run`, `check_prereqs`, `install_python_packages`, `install_browser`, `install_frontend`, `setup_models`, `main`
  <br>`tools/setup.py`

**`update.py`** — get the newest Jarvis without needing git.
  <br>`say`, `main`
  <br>`tools/update.py`

## `verification/`

> Manual scripts that need a LIVE backend. Not pytest — see pyproject.toml for why.

**`_harness.py`** — Jarvis V8 Verification Harness (Final)
  <br>`register_temp`, `cleanup_old_artifacts`, `now_iso`, `ts`, `ram_snapshot`, `save_ram_artifact`, `capture_screenshot`, `process_running`, `dump_process_list`, `dump_ollama_status`, `TestRun`, `guard`
  <br>`verification/_harness.py`

**`run_all_tests.py`** — Jarvis V8 complete verification runner (final).
  <br>`main`
  <br>`verification/run_all_tests.py`

**`test_browser_profile.py`** — Persistent Playwright profile (final).
  <br>`run`
  <br>`verification/test_browser_profile.py`

**`test_chat_persistence.py`** — Chat persistence (final).
  <br>`run`
  <br>`verification/test_chat_persistence.py`

**`test_clickworker.py`** — Verify Clickworker returns REAL tasks, no sample data.
  <br>`run`
  <br>`verification/test_clickworker.py`

**`test_desktop.py`** — Verify desktop control.
  <br>`run`
  <br>`verification/test_desktop.py`

**`test_executor.py`** — Verify bid executor (final).
  <br>`run`
  <br>`verification/test_executor.py`

**`test_health.py`** — Full system health check.
  <br>`run`
  <br>`verification/test_health.py`

**`test_hubstaff.py`** — Verify Hubstaff scraper returns REAL jobs.
  <br>`run`
  <br>`verification/test_hubstaff.py`

**`test_llava.py`** — Verify vision pipeline (final).
  <br>`run`
  <br>`verification/test_llava.py`

**`test_playwright_recovery.py`** — Playwright crash recovery (final).
  <br>`run`
  <br>`verification/test_playwright_recovery.py`

**`test_sse.py`** — Verify SSE live feed.
  <br>`run`
  <br>`verification/test_sse.py`

**`test_v85_wiring.py`** — Verify the four V8.5 structural reconnections.
  <br>`run`
  <br>`verification/test_v85_wiring.py`

**`test_v9_stage1.py`** — Verify V9 Stage 1 control core (LOCKED spec).
  <br>`run`
  <br>`verification/test_v9_stage1.py`

**`test_zuodao.py`** — Verify Zuodao returns REAL tasks, no sample data.
  <br>`run`
  <br>`verification/test_zuodao.py`

