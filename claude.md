# Project Specification: Custom Mail & Calendar Assistant

## Overview
Build a Python-based intelligent assistant that integrates with the Gmail and Google Calendar APIs. The tool acts as a smart executive assistant, utilizing an LLM to process natural language tasks, summarize communications, manage schedules, and draft responses.

## Current State
* `credentials.json` is already configured and downloaded from Google Cloud Console.
* Required APIs (Gmail API, Google Calendar API) are enabled.
* Primary language: Python.

## Core Features Required

### 1. Intelligent Email Summarization & Triage
* Fetch unread emails from the inbox.
* Parse the content to generate concise summaries.
* **Highlighting:** Explicitly flag emails that specifically mention my name or require immediate attention.
* **Deadline Extraction:** Identify actionable dates/deadlines in the text and automatically log them as reminders or calendar events.

### 2. Search and Read
* Implement a search utility that accepts standard Gmail search operators (e.g., `from:someone`, `has:attachment`, `subject:project`).
* Fetch and display the parsed, clean text of selected emails.

### 3. AI-Assisted Drafting & Sending
* Accept a rough text prompt or bulleted draft from the user.
* Use an LLM to refine the tone, expand the context, and format the email professionally.
* **Crucial:** Present the refined draft for explicit user approval (e.g., a Y/N terminal prompt) before executing the Gmail API `send` function.

### 4. Auto-Replies
* Set up logic to trigger automated replies based on specific senders, subjects, or contexts.

### 5. Calendar Management (View)
* Connect to Google Calendar to fetch daily and weekly schedules.
* Display an organized summary of upcoming meetings and events.

### 6. Meeting Scheduling
* Create new Google Calendar events based on natural language inputs (e.g., "Schedule a sync with John next Tuesday at 2 PM").
* **User Prompt for Virtual Link:** During the creation flow, prompt the user with a Y/N input asking if a virtual meeting link should be included. If "Y", automatically generate and attach a Google Meet link (`conferenceDataVersion=1`) to the invite.

## Architecture & Tech Stack Details
* **Google Client:** `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`.
* **LLM Engine:** The summarization, extraction, and drafting modules should be built modularly. This allows the backend to easily swap between a cloud LLM API or a local LLM (e.g., via Ollama, HuggingFace, or LangChain) for processing sensitive inbox data.
* **Authentication:** Standard OAuth2 flow storing a local `token.json` for continuous, background access.

## Implementation Phases
1. **Phase 1: Foundation.** Implement the OAuth2 flow to generate `token.json` and build the `gmail` and `calendar` service objects.
2. **Phase 2: Read & Analyze.** Build the fetch, search, and LLM-parsing functions (summarization, mention-flagging, deadline extraction).
3. **Phase 3: Write & Act.** Build the drafting tool, the user-approval loop, and the auto-reply logic.
4. **Phase 4: Scheduling.** Build the calendar fetch and event creation (with Meet links) functions.
5. **Phase 5: Interface.** Tie it all together into a cohesive CLI loop or a lightweight local web UI.