"""
Document Tools Demo - 文档处理工具集演示
展示如何使用OxyGent的文档处理工具处理PDF、Word、Excel等文档

使用场景：
1. 提取PDF文档内容进行分析
2. 批量处理文档
3. 文档格式转换
4. 文档信息提取


"""

import asyncio
import json
import logging
import os
from pathlib import Path

from oxygent import MAS, Config, oxy, preset_tools

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config():
    """从环境变量加载配置"""
    required_vars = [
        "DEFAULT_LLM_API_KEY",
        "DEFAULT_LLM_BASE_URL",
        "DEFAULT_LLM_MODEL_NAME",
    ]
    
    config = {}
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value is None:
            missing_vars.append(var)
        config[var] = value
    
    if missing_vars:
        raise ValueError(
            f"缺少必需的环境变量: {', '.join(missing_vars)}\n"
            f"请在.env文件或环境中设置这些变量"
        )
    
    return config


# ==================== 示例1：基础文档处理 ====================

async def demo_basic_document_processing():
    """演示基础文档处理功能"""
    print("\n" + "="*70)
    print("示例1：基础文档处理")
    print("="*70)
    
    from oxygent.preset_tools.document_tools import (
        extract_pdf_text,
        read_docx,
        read_excel,
        detect_document_format
    )
    
    # 创建测试文件
    test_dir = Path("./test_documents")
    test_dir.mkdir(exist_ok=True)
    
    # 1. 文档格式检测
    print("\n1. 文档格式检测示例")
    print("-" * 50)
    
    # 假设有一个PDF文件
    test_file = test_dir / "example.pdf"
    if test_file.exists():
        result = detect_document_format(str(test_file))
        result_data = json.loads(result)
        
        if result_data.get('success'):
            print(f"✓ 文件类型: {result_data['format_info']['type']}")
            print(f"✓ 文件大小: {result_data['size_mb']} MB")
            print(f"✓ 是否支持: {result_data['format_info']['supported']}")
            if result_data['format_info']['supported']:
                print(f"✓ 可用工具: {', '.join(result_data['format_info']['tools'])}")
    else:
        print("⚠ 测试文件不存在，跳过此示例")
    
    print("\n提示：将您的PDF/Word/Excel文件放到 ./test_documents 目录进行测试")


# ==================== 示例2：使用Agent处理文档 ====================

async def demo_document_agent():
    """演示使用Agent智能处理文档"""
    print("\n" + "="*70)
    print("示例2：文档处理Agent")
    print("="*70)
    
    try:
        config = load_config()
    except ValueError as e:
        print(f"\n⚠ {e}")
        print("\n跳过Agent示例（需要配置LLM）")
        return
    
    Config.set_agent_llm_model("default_llm")
    
    # 定义Agent系统提示词
    DOCUMENT_AGENT_PROMPT = """
你是一个专业的文档处理助手，擅长处理PDF、Word、Excel等各种文档。

可用工具：
${tools_description}

你的职责：
1. 理解用户的文档处理需求
2. 选择合适的工具完成任务
3. 提供清晰的处理结果和建议

处理流程：
1. 先使用detect_document_format检测文档类型
2. 根据文档类型选择对应的处理工具
3. 提取或处理文档内容
4. 将结果用清晰易懂的方式呈现给用户

当需要调用工具时，使用JSON格式：
```json
{
    "think": "分析和规划",
    "tool_name": "工具名称",
    "arguments": {"参数名": "参数值"}
}
```

处理完成后，用自然语言总结结果。
"""
    
    # 创建oxy空间
    oxy_space = [
        oxy.HttpLLM(
            name="default_llm",
            api_key=config["DEFAULT_LLM_API_KEY"],
            base_url=config["DEFAULT_LLM_BASE_URL"],
            model_name=config["DEFAULT_LLM_MODEL_NAME"],
            llm_params={"temperature": 0.1},
        ),
        preset_tools.document_tools,
        oxy.ReActAgent(
            name="document_agent",
            desc="专业的文档处理助手，可以处理PDF、Word、Excel等文档",
            tools=["document_tools"],
            prompt=DOCUMENT_AGENT_PROMPT,
        ),
    ]
    
    print("\n✓ Agent已创建，可以处理文档相关任务")
    print("\n示例任务：")
    print("  - '帮我分析这个PDF文件的内容'")
    print("  - '提取Word文档中的所有表格'")
    print("  - '读取Excel第二个工作表的数据'")
    print("  - '合并这两个PDF文件'")
    
    # 启动交互式服务
    query = "请介绍一下你能处理哪些类型的文档，以及每种文档的处理能力。"
    
    async with MAS(oxy_space=oxy_space) as mas:
        print(f"\n📝 测试查询: {query}")
        print("\n启动Web服务...")
        await mas.start_web_service(first_query=query)


# ==================== 示例3：批量文档处理 ====================

async def demo_batch_processing():
    """演示批量处理多个文档"""
    print("\n" + "="*70)
    print("示例3：批量文档处理")
    print("="*70)
    
    from oxygent.preset_tools.document_tools import (
        extract_pdf_text,
        get_pdf_info,
        detect_document_format
    )
    
    # 模拟批量处理场景
    test_dir = Path("./test_documents")
    
    if not test_dir.exists():
        print("\n创建测试目录...")
        test_dir.mkdir(exist_ok=True)
    
    # 查找所有文档文件
    doc_patterns = ["*.pdf", "*.docx", "*.xlsx"]
    all_docs = []
    
    for pattern in doc_patterns:
        all_docs.extend(test_dir.glob(pattern))
    
    if not all_docs:
        print("\n⚠ 未找到测试文档")
        print("  请将文档文件放到 ./test_documents 目录")
        print("  支持格式: PDF, Word(.docx), Excel(.xlsx)")
        return
    
    print(f"\n找到 {len(all_docs)} 个文档文件")
    print("-" * 50)
    
    results = []
    
    for doc_path in all_docs:
        print(f"\n处理: {doc_path.name}")
        
        # 1. 检测格式
        format_result = detect_document_format(str(doc_path))
        format_data = json.loads(format_result)
        
        if not format_data.get('success'):
            print(f"  ✗ 格式检测失败")
            continue
        
        doc_type = format_data['format_info']['type']
        print(f"  类型: {doc_type}")
        print(f"  大小: {format_data['size_mb']} MB")
        
        # 2. 根据类型处理
        if doc_type == 'PDF' and format_data['format_info']['supported']:
            # 获取PDF信息
            info_result = get_pdf_info(str(doc_path))
            info_data = json.loads(info_result)
            
            if info_data.get('success'):
                print(f"  页数: {info_data['document_properties']['page_count']}")
                print(f"  图像数: {info_data['content_statistics']['total_images']}")
                
                results.append({
                    "file": doc_path.name,
                    "type": doc_type,
                    "pages": info_data['document_properties']['page_count'],
                    "status": "success"
                })
    
    # 3. 生成报告
    if results:
        print("\n" + "="*70)
        print("批处理报告")
        print("="*70)
        print(f"\n处理成功: {len(results)} 个文档")
        print(f"总页数: {sum(r.get('pages', 0) for r in results)}")
        
        # 保存报告
        report_path = test_dir / "batch_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {report_path}")


# ==================== 示例4：文档内容分析 ====================

async def demo_document_analysis_agent():
    """演示文档内容智能分析Agent"""
    print("\n" + "="*70)
    print("示例4：文档内容分析Agent（高级示例）")
    print("="*70)
    
    try:
        config = load_config()
    except ValueError as e:
        print(f"\n⚠ {e}")
        print("\n跳过此示例（需要配置LLM）")
        return
    
    Config.set_agent_llm_model("default_llm")
    
    # 文档分析Agent的系统提示词
    ANALYSIS_AGENT_PROMPT = """
你是一个专业的文档分析专家，能够深入分析各种文档的内容。

可用工具：
${tools_description}

分析流程：
1. 接收文档路径
2. 使用detect_document_format识别文档类型
3. 根据类型使用对应工具提取内容
4. 深入分析文档内容，提供：
   - 文档概要
   - 关键信息提取
   - 结构分析
   - 内容建议

特殊能力：
- PDF：提取文本、表格、图像，分析文档结构
- Word：分析段落结构、提取表格数据
- Excel：分析数据分布、统计信息

输出格式：
```json
{
    "think": "思考过程",
    "tool_name": "工具名",
    "arguments": {...}
}
```

分析完成后，提供结构化的分析报告。
"""
    
    oxy_space = [
        oxy.HttpLLM(
            name="default_llm",
            api_key=config["DEFAULT_LLM_API_KEY"],
            base_url=config["DEFAULT_LLM_BASE_URL"],
            model_name=config["DEFAULT_LLM_MODEL_NAME"],
            llm_params={"temperature": 0.2},
        ),
        preset_tools.document_tools,
        preset_tools.file_tools,  # 用于保存分析报告
        oxy.ReActAgent(
            name="analysis_agent",
            desc="文档内容深度分析专家，提供专业的文档分析报告",
            tools=["document_tools", "file_tools"],
            prompt=ANALYSIS_AGENT_PROMPT,
        ),
    ]
    
    print("\n✓ 文档分析Agent已创建")
    print("\n功能：")
    print("  - 自动识别文档类型")
    print("  - 提取文档关键信息")
    print("  - 生成结构化分析报告")
    print("  - 提供内容改进建议")
    
    # 示例任务
    query = """
请分析文档处理工具的能力，并说明：
1. 支持哪些文档格式
2. 每种格式有哪些处理功能
3. 典型使用场景
4. 最佳实践建议
"""
    
    async with MAS(oxy_space=oxy_space) as mas:
        print(f"\n📊 分析任务: {query}")
        print("\n启动分析服务...")
        await mas.start_web_service(first_query=query)


# ==================== 示例5：直接调用工具API ====================

async def demo_direct_tool_usage():
    """演示直接调用工具API（不使用Agent）"""
    print("\n" + "="*70)
    print("示例5：直接调用工具API")
    print("="*70)
    
    from oxygent.preset_tools.document_tools import (
        extract_pdf_text,
        get_pdf_info,
        merge_pdfs,
        split_pdf
    )
    
    print("\n这是最简单的使用方式，适合脚本化处理")
    print("-" * 50)
    
    # 创建示例代码
    example_code = '''
# 示例1: 提取PDF文本
from oxygent.preset_tools.document_tools import extract_pdf_text
import json

result = extract_pdf_text("document.pdf", page_range="1-5")
data = json.loads(result)

if data['success']:
    for page in data['pages']:
        print(f"第{page['page_number']}页:")
        print(page['text'])

# 示例2: 获取PDF信息
from oxygent.preset_tools.document_tools import get_pdf_info

result = get_pdf_info("document.pdf")
data = json.loads(result)

print(f"总页数: {data['document_properties']['page_count']}")
print(f"作者: {data['document_metadata']['author']}")

# 示例3: 合并PDF
from oxygent.preset_tools.document_tools import merge_pdfs

result = merge_pdfs(
    pdf_paths=["file1.pdf", "file2.pdf", "file3.pdf"],
    output_path="merged.pdf"
)

# 示例4: 拆分PDF
from oxygent.preset_tools.document_tools import split_pdf

result = split_pdf(
    path="large.pdf",
    split_ranges=["1-10", "11-20", "21-30"],
    output_dir="./split_output"
)

# 示例5: 读取Word文档
from oxygent.preset_tools.document_tools import read_docx

result = read_docx("report.docx")
data = json.loads(result)

for para in data['paragraphs']:
    print(para['text'])

# 示例6: 读取Excel
from oxygent.preset_tools.document_tools import read_excel

result = read_excel("data.xlsx", sheet_name="Sheet1", max_rows=50)
data = json.loads(result)

print(f"表头: {data['headers']}")
for row in data['rows']:
    print(row)
'''
    
    print("\n直接调用示例代码：")
    print("-" * 50)
    print(example_code)
    print("-" * 50)
    
    print("\n优势：")
    print("  ✓ 代码简洁，易于理解")
    print("  ✓ 性能最优，无LLM调用开销")
    print("  ✓ 适合批量处理和自动化脚本")
    print("  ✓ 返回结构化JSON，便于程序处理")


# ==================== 主菜单 ====================

async def main():
    """主函数 - 展示所有示例"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║          OxyGent 文档处理工具集 - 完整演示                        ║
╚══════════════════════════════════════════════════════════════════╝

本演示展示了OxyGent框架中文档处理工具的各种使用方式：
  
  示例1: 基础文档处理功能
  示例2: 使用Agent智能处理文档  
  示例3: 批量文档处理
  示例4: 文档内容智能分析（高级）
  示例5: 直接调用工具API
  
注意：
  - 示例2和4需要配置LLM环境变量
  - 测试文档请放在 ./test_documents 目录
  - 支持格式: PDF, Word(.docx), Excel(.xlsx)
""")
    
    try:
        # 依次运行所有示例
        await demo_basic_document_processing()
        
        await demo_batch_processing()
        
        await demo_direct_tool_usage()
        
        # 需要LLM的示例
        print("\n" + "="*70)
        print("需要LLM配置的高级示例")
        print("="*70)
        
        await demo_document_agent()
        
        await demo_document_analysis_agent()
        
        print("\n" + "="*70)
        print("✓ 所有示例演示完成！")
        print("="*70)
        print("\n下一步：")
        print("  1. 安装依赖: pip install PyMuPDF pdfplumber python-docx openpyxl")
        print("  2. 准备测试文档放到 ./test_documents 目录")
        print("  3. 配置LLM环境变量（如需使用Agent功能）")
        print("  4. 运行测试: python examples/tools/demo_document_tools.py")
        print("\n查看更多信息: docs/document_tools/README_document_tools.md")
        
    except KeyboardInterrupt:
        print("\n\n⚠ 演示已取消")
    except Exception as e:
        logger.error(f"演示过程出错: {e}", exc_info=True)
        print(f"\n✗ 错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())

