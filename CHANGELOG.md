# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Added support for dynamic registration of `oxy`

---

## [1.0.9.3] - 2025-12-12
### Added
- Added oxy.BaseLLM parameter to support custom multimodal base64 prefixes.
- Added func_process_message method to the MAS class for unified message processing, refer to [./examples/backend/demo_process_message.py](./examples/backend/demo_process_message.py)

### Fixed
- When the send_msg_key parameter of the chat_with_agent function is empty, messages will not be sent.

---

## [1.0.9.2] - 2025-12-09
### Added
- Added stream_end message as an indicator for the end of streaming messages.
- Stream messages now support batch storage.

### Changed
- Modified the structure of the message table, added new fields.

---

## [1.0.9.1] - 2025-12-04
### Added
- Added pre-logging of payloads for easier troubleshooting.
- Standardized SSE message fields: id, event, data.
- SSEOxyGent now forwards headers transparently.

### Changed
- When storing in the history table, the answer field in memory is forcibly converted to a string.

---

## [1.0.8] - 2025-11-14

### Added
- Added streaming output capability to the frontend
- Added Agent name field to think messages

### Changed
- LChanged the default value of the LLM parameter stream to True

---
## [1.0.6.3] - 2025-10-15

### Added
- Added fine-grained message storage, refer to [./examples/advanced/demo_save_message.py](./examples/advanced/demo_save_message.py)

### Changed
- Updated examples. For details, see [./examples](./examples)

---

## [1.0.6.2] - 2025-10-09

### Added
- Added an example of a custom agent input schema, refer to [./examples/advanced/demo_custom_agent_input_schema.py](./examples/advanced/demo_custom_agent_input_schema.py)

### Changed
- Renamed Vearch configuration parameter `tool_df_space_name` to `tool_space_name`
- Modified the names of environment variables used in `config.json`

---

## [1.0.6.1] - 2025-09-30

### Added
- Added multimodal information transfer mechanism between agents, refer to [./examples/advanced/demo_multimodal_transfer.py](./examples/advanced/demo_multimodal_transfer.py)

### Changed
- Automatically generate externally accessible Web links after uploading attachments

### Fixed
- Fixed the issue where multiple interactions between agents in a single conversation were not correctly recorded in history

### Removed
- Removed support for `web_file_url_list` in `payload`
