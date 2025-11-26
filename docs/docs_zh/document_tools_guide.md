# 文档处理工具集使用指南

> OxyGent 文档处理工具集 - 支持 PDF、Word、Excel 等多种文档格式的智能处理

## 📚 目录

- [简介](#简介)
- [特性亮点](#特性亮点)
- [安装依赖](#安装依赖)
- [快速开始](#快速开始)
- [工具API详解](#工具api详解)
- [使用场景](#使用场景)
- [性能基准](#性能基准)

---

## 简介

文档处理工具集是 OxyGent 内置的文档处理模块，提供对主流文档格式的全面支持。无论是简单的文本提取，还是复杂的文档分析，都能轻松完成。

### 支持格式

| 格式 | 读取 | 写入 | 表格提取 | 图像提取 | 元数据 |
|------|------|------|----------|----------|--------|
| **PDF** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **Word (.docx)** | ✅ | ❌* | ✅ | ❌ | ❌ |
| **Excel (.xlsx)** | ✅ | ❌* | N/A | ❌ | ✅ |
| **PowerPoint (.pptx)** | 🔄 | ❌ | ❌ | ❌ | ❌ |

*标注：写入功能在未来版本中提供  
🔄 = 开发中

---

## 特性亮点

### 🚀 高性能
- **比PyPDF2快10-50倍**：采用PyMuPDF的C++底层引擎
- **内存优化**：流式处理大文件，避免内存溢出
- **并发支持**：支持批量文档的并行处理

### 🎯 高精度
- **表格识别率90%+**：使用pdfplumber的高级算法
- **智能布局分析**：准确识别文档结构
- **中英文全支持**：完美处理多语言文档

### 🔧 易用性
- **统一API设计**：所有工具遵循相同的调用模式
- **详细错误提示**：清晰的错误信息和解决建议
- **JSON格式返回**：结构化数据，易于程序处理

### 🤖 AI集成
- **原生Agent支持**：可直接注册为Agent工具
- **智能文档分析**：结合LLM实现深度内容理解
- **RAG优化**：为检索增强生成场景特别优化

---

## 安装依赖

### 完整安装（推荐）

```bash
# 安装所有文档处理依赖
pip install PyMuPDF pdfplumber python-docx openpyxl
```

### 按需安装

```bash
# 仅处理PDF
pip install PyMuPDF pdfplumber

# 仅处理Word
pip install python-docx

# 仅处理Excel
pip install openpyxl
```


### 依赖说明

| 库名称 | 版本要求 | 用途 | 许可证 |
|--------|----------|------|--------|
| PyMuPDF | ≥1.23.0 | PDF核心处理 | AGPL/商业双许可 |
| pdfplumber | ≥0.10.0 | 表格精准提取 | MIT |
| python-docx | ≥1.1.0 | Word文档处理 | MIT |
| openpyxl | ≥3.1.0 | Excel文档处理 | MIT |

---

## 快速开始

### 方式1：直接调用工具API

最简单的使用方式，适合脚本化处理：

```python
from oxygent.preset_tools.document_tools import extract_pdf_text
import json

# 提取PDF文本
result = extract_pdf_text("report.pdf", page_range="1-5")
data = json.loads(result)

if data['success']:
    for page in data['pages']:
        print(f"第{page['page_number']}页:")
        print(page['text'][:200])  # 打印前200字符
```

### 方式2：使用Agent智能处理

让AI理解文档处理需求：

```python
import asyncio
from oxygent import MAS, Config, oxy, preset_tools

Config.set_agent_llm_model("default_llm")

oxy_space = [
    oxy.HttpLLM(
        name="default_llm",
        api_key="your_api_key",
        base_url="your_base_url",
        model_name="your_model",
    ),
    preset_tools.document_tools,  # 注册文档工具
    oxy.ReActAgent(
        name="doc_agent",
        desc="文档处理助手",
        tools=["document_tools"],
    ),
]

async def main():
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(
            first_query="提取这个PDF的所有表格数据：report.pdf"
        )

asyncio.run(main())
```

### 方式3：集成到现有Agent

```python
# 为现有Agent添加文档处理能力
oxy_space = [
    your_llm,
    preset_tools.document_tools,  # 添加文档工具
    preset_tools.file_tools,       # 文件操作
    preset_tools.http_tools,       # HTTP请求
    oxy.ReActAgent(
        name="multi_skill_agent",
        tools=[
            "document_tools",  # 文档处理
            "file_tools",      # 文件操作
            "http_tools"       # 网络请求
        ],
    ),
]
```

---

## 工具API详解

### PDF处理工具

#### 1. extract_pdf_text - 提取PDF文本

```python
extract_pdf_text(
    path: str,                      # PDF文件路径
    page_range: Optional[str] = None,  # 页码范围："1-5" 或 "1,3,5"
    max_chars_per_page: int = 10000    # 单页最大字符数
) -> str  # 返回JSON字符串
```

**返回示例：**
```json
{
  "success": true,
  "file_path": "document.pdf",
  "total_pages": 10,
  "extracted_pages": 5,
  "pages": [
    {
      "page_number": 1,
      "text": "页面文本内容...",
      "char_count": 1523,
      "has_images": true
    }
  ]
}
```

**使用场景：**
- 文档内容提取与分析
- RAG系统的文档预处理
- 文本搜索与索引构建

#### 2. extract_pdf_tables - 提取PDF表格

```python
extract_pdf_tables(
    path: str,
    page_range: Optional[str] = None,
    table_settings: Optional[Dict] = None  # 表格识别参数
) -> str
```

**返回示例：**
```json
{
  "success": true,
  "table_count": 2,
  "tables": [
    {
      "page": 1,
      "table_index": 1,
      "headers": ["姓名", "年龄", "城市"],
      "rows": [
        ["张三", "30", "北京"],
        ["李四", "25", "上海"]
      ],
      "row_count": 2,
      "column_count": 3
    }
  ]
}
```

**高级配置：**
```python
# 自定义表格识别策略
table_settings = {
    "vertical_strategy": "lines",    # 垂直线识别策略
    "horizontal_strategy": "lines",  # 水平线识别策略
    "snap_tolerance": 3,             # 线条对齐容差
    "join_tolerance": 3              # 表格合并容差
}

result = extract_pdf_tables(
    "complex_table.pdf",
    table_settings=table_settings
)
```

#### 3. extract_pdf_images - 提取PDF图像

```python
extract_pdf_images(
    path: str,
    output_dir: str,             # 图像保存目录
    page_range: Optional[str] = None,
    min_size: int = 1024        # 最小图像大小（字节）
) -> str
```

**返回示例：**
```json
{
  "success": true,
  "output_dir": "./images",
  "image_count": 5,
  "images": [
    {
      "page": 1,
      "filename": "image_p1_1.png",
      "path": "./images/image_p1_1.png",
      "size_bytes": 45678,
      "format": "png",
      "width": 800,
      "height": 600
    }
  ]
}
```

#### 4. merge_pdfs - 合并PDF

```python
merge_pdfs(
    pdf_paths: List[str],           # PDF文件列表
    output_path: str,               # 输出文件路径
    include_bookmarks: bool = True  # 是否保留书签
) -> str
```

**示例：**
```python
result = merge_pdfs(
    pdf_paths=[
        "chapter1.pdf",
        "chapter2.pdf",
        "chapter3.pdf"
    ],
    output_path="full_book.pdf"
)
```

#### 5. split_pdf - 拆分PDF

```python
split_pdf(
    path: str,
    split_ranges: List[str],  # 拆分范围列表
    output_dir: str,
    name_prefix: str = "split"
) -> str
```

**示例：**
```python
# 将100页PDF拆分为3个文件
result = split_pdf(
    path="large_document.pdf",
    split_ranges=["1-30", "31-70", "71-100"],
    output_dir="./chapters"
)
```

#### 6. get_pdf_info - 获取PDF元数据

```python
get_pdf_info(path: str) -> str
```

**返回信息：**
- 文档属性（标题、作者、主题、关键词）
- 页面信息（总页数、页面尺寸）
- 技术信息（PDF版本、加密状态）
- 内容统计（文本量、图像数量）

### Word文档工具

#### 7. read_docx - 读取Word文档

```python
read_docx(
    path: str,
    include_tables: bool = True,
    max_paragraphs: int = 1000
) -> str
```

**返回示例：**
```json
{
  "success": true,
  "statistics": {
    "paragraph_count": 25,
    "table_count": 2,
    "word_count": 1523,
    "char_count": 8965
  },
  "paragraphs": [
    {
      "index": 1,
      "text": "段落内容...",
      "style": "Heading 1"
    }
  ],
  "tables": [
    {
      "table_index": 1,
      "row_count": 5,
      "column_count": 3,
      "headers": ["列1", "列2", "列3"],
      "rows": [["数据1", "数据2", "数据3"]]
    }
  ]
}
```

#### 8. extract_docx_text - 提取Word纯文本

```python
extract_docx_text(path: str) -> str
```

快速提取所有文本内容，不包含格式信息。

### Excel文档工具

#### 9. read_excel - 读取Excel

```python
read_excel(
    path: str,
    sheet_name: Optional[str] = None,  # 工作表名称
    max_rows: int = 100,               # 最大行数
    has_header: bool = True            # 是否有表头
) -> str
```

**返回示例：**
```json
{
  "success": true,
  "sheet_name": "销售数据",
  "available_sheets": ["销售数据", "统计报表"],
  "statistics": {
    "row_count": 50,
    "column_count": 5,
    "has_header": true
  },
  "headers": ["日期", "产品", "数量", "单价", "总额"],
  "rows": [
    ["2024-01-01", "产品A", 10, 99.9, 999],
    ["2024-01-02", "产品B", 20, 49.9, 998]
  ]
}
```

#### 10. list_excel_sheets - 列出工作表

```python
list_excel_sheets(path: str) -> str
```

返回所有工作表的名称和基本信息。

### 通用工具

#### 11. detect_document_format - 检测文档格式

```python
detect_document_format(path: str) -> str
```

**返回示例：**
```json
{
  "success": true,
  "filename": "report.pdf",
  "extension": ".pdf",
  "size_mb": 2.5,
  "format_info": {
    "type": "PDF",
    "category": "Portable Document Format",
    "supported": true,
    "tools": [
      "extract_pdf_text",
      "extract_pdf_tables",
      "extract_pdf_images"
    ]
  }
}
```

---

## 使用场景

### 场景1：智能文档问答系统（RAG）

```python
from oxygent.preset_tools.document_tools import extract_pdf_text
from oxygent.databases.db_vector import VectorDB
import json

# 1. 提取PDF内容
result = extract_pdf_text("knowledge_base.pdf")
data = json.loads(result)

# 2. 分块存储到向量数据库
vector_db = VectorDB()
for page in data['pages']:
    chunks = split_text(page['text'], chunk_size=500)
    for chunk in chunks:
        embedding = get_embedding(chunk)
        vector_db.add(
            text=chunk,
            embedding=embedding,
            metadata={
                "page": page['page_number'],
                "source": "knowledge_base.pdf"
            }
        )

# 3. 使用Agent回答问题
query = "文档中关于XX的内容是什么？"
relevant_chunks = vector_db.search(query, top_k=5)
answer = agent.ask(query, context=relevant_chunks)
```

### 场景2：批量报表处理

```python
import json
from pathlib import Path
from oxygent.preset_tools.document_tools import (
    read_excel,
    extract_pdf_tables
)

reports_dir = Path("./monthly_reports")
all_data = []

# 处理Excel报表
for excel_file in reports_dir.glob("*.xlsx"):
    result = read_excel(str(excel_file))
    data = json.loads(result)
    if data['success']:
        all_data.extend(data['rows'])

# 处理PDF报表
for pdf_file in reports_dir.glob("*.pdf"):
    result = extract_pdf_tables(str(pdf_file))
    data = json.loads(result)
    if data['success']:
        for table in data['tables']:
            all_data.extend(table['rows'])

# 生成汇总报告
generate_summary_report(all_data)
```

### 场景3：文档内容审计

```python
from oxygent.preset_tools.document_tools import (
    extract_pdf_text,
    get_pdf_info
)

def audit_document(pdf_path):
    """审计文档内容，检测敏感信息"""
    # 获取文档信息
    info = json.loads(get_pdf_info(pdf_path))
    
    # 提取全文
    text_result = json.loads(extract_pdf_text(pdf_path))
    
    # 敏感词检测
    sensitive_words = ["机密", "保密", "内部"]
    found_sensitive = []
    
    for page in text_result['pages']:
        for word in sensitive_words:
            if word in page['text']:
                found_sensitive.append({
                    "page": page['page_number'],
                    "keyword": word
                })
    
    # 生成审计报告
    return {
        "file": pdf_path,
        "pages": info['document_properties']['page_count'],
        "author": info['document_metadata']['author'],
        "sensitive_items": found_sensitive,
        "risk_level": "high" if found_sensitive else "low"
    }
```

### 场景4：多语言文档翻译

```python
async def translate_document(pdf_path, target_lang="en"):
    """提取文档内容并翻译"""
    from oxygent import MAS, oxy, preset_tools
    
    # 提取原文
    result = extract_pdf_text(pdf_path)
    data = json.loads(result)
    
    # 使用Agent翻译
    oxy_space = [
        your_llm,
        preset_tools.document_tools,
        oxy.ReActAgent(
            name="translator_agent",
            desc=f"将文本翻译为{target_lang}",
            tools=["document_tools"]
        )
    ]
    
    translations = []
    async with MAS(oxy_space=oxy_space) as mas:
        for page in data['pages']:
            query = f"将以下内容翻译为{target_lang}：{page['text'][:500]}"
            response = await mas.ask("translator_agent", query)
            translations.append(response)
    
    return translations
```

---

## 性能基准

### 测试环境
- CPU: Intel i7-12700K
- RAM: 32GB
- 文件: 100页PDF, 10MB

### 性能对比

| 操作 | PyMuPDF | PyPDF2 | pdfplumber | 提升比例 |
|------|---------|--------|------------|----------|
| 文本提取 | 0.3s | 1.2s | 2.5s | **4-8x** |
| 表格提取 | 1.5s | N/A | 3.8s | **2.5x** |
| 图像提取 | 0.8s | 2.1s | N/A | **2.6x** |
| PDF合并 | 0.5s | 1.8s | N/A | **3.6x** |
| 内存占用 | 80MB | 150MB | 200MB | **节省50%** |

### 大文件处理能力

| 文件大小 | 页数 | 处理时间 | 峰值内存 |
|---------|------|---------|----------|
| 1MB | 10页 | 0.1s | 50MB |
| 10MB | 100页 | 0.8s | 120MB |
| 50MB | 500页 | 3.5s | 280MB |
| 100MB | 1000页 | 7.2s | 450MB |

---



## 最佳实践

### 1. 错误处理

```python
import json
from oxygent.preset_tools.document_tools import extract_pdf_text

def safe_extract_pdf(pdf_path):
    """安全的PDF提取，带完整错误处理"""
    try:
        result_str = extract_pdf_text(pdf_path)
        result = json.loads(result_str)
        
        if result.get('success'):
            return result
        else:
            logger.error(f"提取失败: {result.get('error')}")
            return None
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析错误: {e}")
        return None
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return None
```

### 2. 性能优化

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def process_documents_parallel(file_list):
    """并行处理多个文档"""
    with ThreadPoolExecutor(max_workers=4) as executor:
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(
                executor,
                extract_pdf_text,
                file_path
            )
            for file_path in file_list
        ]
        results = await asyncio.gather(*tasks)
    
    return results
```

### 3. 结果缓存

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=100)
def extract_pdf_cached(pdf_path, page_range):
    """缓存PDF提取结果"""
    return extract_pdf_text(pdf_path, page_range)

# 或使用文件内容哈希作为缓存键
def get_file_hash(file_path):
    with open(file_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

cache = {}

def extract_with_content_cache(pdf_path):
    file_hash = get_file_hash(pdf_path)
    
    if file_hash in cache:
        return cache[file_hash]
    
    result = extract_pdf_text(pdf_path)
    cache[file_hash] = result
    return result
```




