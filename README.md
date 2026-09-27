# Vikunja for Home Assistant

Author: [MarshyMadness](https://github.com/Marshy-Madness)

A Home Assistant integration for [Vikunja](https://vikunja.io/), the self-hosted task manager.

## Features

- **A to-do list per Vikunja project**. Add, complete, edit and delete tasks from Home Assistant.
- **Sensors**: open tasks, overdue tasks, due today, due this week, high-priority tasks, and next due.
- **Calendar** of task due dates.
- **Actions**: `vikunja.create_task`, `vikunja.get_tasks` (returns the tasks), and `vikunja.add_comment`.

## Setup

Create an API token in Vikunja under *Settings → API Tokens* with these permissions:

- Projects: read all
- Tasks: read all, read one, create, update, delete
- Labels: read all
- Tasks Labels: bulk
- Tasks Comments: create

Then add the integration and enter your Vikunja URL and the token.

## Install

### HACS

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/Marshy-Madness/ha-vikunja` as an **Integration**.
2. Install **Vikunja** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Vikunja*.

### Manual

Copy `custom_components/vikunja` into `<config>/custom_components/` and restart Home Assistant.
