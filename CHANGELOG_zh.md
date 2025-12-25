# Changelog

所有重要变更将在此文件中记录。

## [Unreleased]

### Added
- 新增支持动态注册 `oxy`

---

## [1.0.10.4] - 2025-12-24

### Added
- 新增Prompt管理界面，支持在线修改Prompt

### Changed
- 修改es包，由elasticsearch[async] 改为 elasticsearch

---

## [1.0.10.3] - 2025-12-23

### Added
- 支持异步接口：发起任务接口 /async/chat，以及查询结果接口 /async/trace
- 支持 SSE 重试的指数退避机制

---

## [1.0.10.2] - 2025-12-18

### Changed
- 修改描述附件的格式

---

## [1.0.10.1] - 2025-12-17

### Added
- 新增用户反馈接口/feedback，用于实现human-in-the-loop，详见 [./examples/backend/demo_human_in_the_loop.py](./examples/backend/demo_human_in_the_loop.py)

---

## [1.0.9.3] - 2025-12-12

### Added
- 新增oxy.BaseLLM参数，支持自定义多模态base64前缀
- MAS类新增func_process_message方法，用于统一处理消息，详见 [./examples/backend/demo_process_message.py](./examples/backend/demo_process_message.py)

### Fixed
- chat_with_agent函数入参send_msg_key参数为空时，修改为不发送消息

---

## [1.0.9.2] - 2025-12-09

### Added
- 新增流式消息结束标识的stream_end消息
- stream消息支持分批存储

### Changed
- 修改message表结构，新增字段

---

## [1.0.9.1] - 2025-12-04

### Added
- 前置打印payload日志，便于排除
- 标准化sse消息字段id、event、data
- SSEOxyGent透传headers

### Changed
- history表存储时，memory的answer字段强转str

---

## [1.0.8] - 2025-11-14

### Added
- 新增前端的流式输出能力

### Changed
- LLM参数 stream 默认值修改为 True
- think消息 增加 Agent 名称字段

---

## [1.0.6.3] - 2025-10-15

### Added
- 新增细粒度的消息存储，详见 [./examples/advanced/demo_save_message.py](./examples/advanced/demo_save_message.py)

### Changed
- 更新示例，详见 [./examples](./examples)

---

## [1.0.6.2] - 2025-10-09

### Added
- 新增自定义智能体输入结构体示例，详见 [./examples/advanced/demo_custom_agent_input_schema.py](./examples/advanced/demo_custom_agent_input_schema.py)

### Changed
- Vearch 配置参数 `tool_df_space_name` 更名为 `tool_space_name`
- 修改 `config.json` 中引用的环境变量名称

---

## [1.0.6.1] - 2025-09-30

### Added
- 新增智能体之间的多模态信息传递机制，详见 [./examples/advanced/demo_multimodal_transfer.py](./examples/advanced/demo_multimodal_transfer.py)

### Changed
- 上传附件后，自动生成外部可访问的 Web 链接

### Fixed
- 修复一轮对话中，多智能体之间多次交互未正确记录历史的问题

### Removed
- 移除对 `payload` 中 `web_file_url_list` 的支持
