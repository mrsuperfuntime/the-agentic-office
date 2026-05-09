# IT Office

## Overview

The IT Office manages platform integrations, creative APIs, and publishing connectors used by the Social Media Office.

## Responsibilities

- Link and track platform integrations (X, Instagram, LinkedIn, TikTok, Facebook)
- Link and track creative API integrations, starting with Meshy AI API
- Store integration metadata for local development
- Accept publish requests from social-media workflows
- Execute role-aware IT workflow stages for integration-review and 3D model generation
- Record publish artifacts into the data output folder

## API Endpoints

- GET /health
- GET /manager
- GET /integrations
- GET /integrations/catalog
- POST /integrations/link
- POST /integrations/unlink
- POST /publish
- POST /handle-request

Common `POST /handle-request` actions:

- `validate_publish_ready`
- `validate_integration_ready`
- `generate_3d_model`
- `link_integration`
- `list_integrations`

## Supported Integrations

- X
- Instagram
- LinkedIn
- TikTok
- Facebook
- Meshy AI API

## Environment Variables

- IT_OUTPUT_ROOT: Root folder for IT artifacts (default: ../../data-output/it-office)
- IT_INTEGRATIONS_FILE: Optional explicit path for integrations store JSON

## Security Model

- Integrations store vault-style credential references such as `vault://social/x/account-name`
- Meshy uses the `vault://ai/meshy/...` scope by default
- Raw API keys are not persisted in the integration metadata file

## Built-In Logic Flows

- Integration review stage: validates and links requested integrations from workflow context
- Social publish readiness: validates publish-capable platforms before IT publish execution
- Meshy 3D generation: validates Meshy integration, emits queued job artifacts, and returns job metadata
- Shenanigans lab support: provides integration/runtime services for experimental cross-office workflows

## Running

```bash
python main.py
```
