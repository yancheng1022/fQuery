# 扫描件 PDF 表格提取工具

从扫描版 PDF（图纸/工程表格）中识别表格，写入 SQLite，便于后续搜索。

## 功能

- 支持扫描件：线条检测 + PaddleOCR 中文识别
- 自动跳过无数据表的图纸页
- 保存表名、行列内容到 SQLite，并建立 FTS 全文索引
- 图形界面：提取、预览、关键词搜索
- 也可命令行批量处理

## 安装

```bash
pip install -r requirements.txt
```

首次运行会自动下载 OCR 模型（需联网）。

## 使用

### 图形界面

```bash
python main.py
```

### 命令行（建议先试几页）

```bash
python main.py --cli --pdf "S4-7 涵洞.pdf" --db "S4-7_tables.db" --page-from 5 --page-to 6
```

## SQLite 结构

| 表 | 说明 |
|---|---|
| `documents` | PDF 文件信息 |
| `tables` | 表名、页码、完整内容 JSON/`content_text` |
| `cells` | 单元格级文本，便于精确检索 |
| `tables_fts` | FTS5 全文索引 |

示例查询：

```sql
SELECT table_name, page_number FROM tables WHERE content_text LIKE '%填土高度%';
SELECT * FROM tables_fts WHERE tables_fts MATCH '斜管节';
```

## 说明

- CPU 环境下，含表格的页面 OCR 大约每页 1 分钟；无表格页会快速跳过
- 复杂合并单元格可能偶有错位，可在界面预览后按页重跑
