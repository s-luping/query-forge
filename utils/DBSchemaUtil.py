import re
import csv
import pymysql
import os


class DBSchemaUtil:
    """数据库Schema工具类 - 从外部数据库读取DDL并生成CSV"""
    
    def __init__(self, db_config, tables=None):
        self.db_config = db_config
        self.tables = tables
        self.conn = None

    def test_connection(self):
        """测试数据库连接"""
        try:
            self.conn = pymysql.connect(**self.db_config)
            print(f"成功连接到数据库: {self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}")
            return True
        except Exception as e:
            print(f"数据库连接失败: {e}")
            return False

    def get_table_list(self, database=None):
        """获取数据库表列表"""
        if not self.conn:
            if not self.test_connection():
                return []

        tables = []
        try:
            with self.conn.cursor() as cursor:
                if database:
                    cursor.execute(f"USE {database}")
                cursor.execute("SHOW TABLES")
                tables = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取表列表失败: {e}")
        return tables

    def get_ddl(self, table_name, database=None):
        """获取表的DDL语句"""
        if not self.conn:
            if not self.test_connection():
                return ""

        try:
            with self.conn.cursor() as cursor:
                if database:
                    cursor.execute(f"USE `{database}`")
                cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
                result = cursor.fetchone()
                if result:
                    return result[1]
        except Exception as e:
            print(f"获取DDL失败: {e}")
        return ""

    def parse_ddl(self, ddl, db_id):
        """解析DDL语句"""
        table_name_match = re.search(r'CREATE TABLE `([^`]+)`', ddl)
        table_name = table_name_match.group(1) if table_name_match else ''

        table_comment_match = re.search(r'COMMENT=[\'\"]([^\'\"]+)[\'\"]', ddl)
        if not table_comment_match:
            table_comment_match = re.search(r'COMMENT\s*=\s*[\'\"]([^\'\"]+)[\'\"]', ddl)
        table_comment = table_comment_match.group(1) if table_comment_match else ''

        pk_match = re.findall(r'PRIMARY KEY \(([^)]+)\)', ddl)
        primary_key = pk_match[0] if pk_match else ''

        fk_match = re.findall(r'FOREIGN KEY \(([^)]+)\)', ddl)
        foreign_key = fk_match[0] if fk_match else ''

        columns = []

        table_struct_match = re.search(r'\(([\s\S]+)\) ENGINE', ddl)
        if table_struct_match:
            table_struct = table_struct_match.group(1)
            for line in table_struct.split('\n'):
                line = line.strip()
                if not line or line.startswith('PRIMARY KEY') or line.startswith('FOREIGN KEY') or line.startswith('KEY'):
                    continue
                if line.endswith(','):
                    line = line[:-1].strip()

                col_name_match = re.match(r'`([^`]+)`', line)
                if not col_name_match:
                    continue
                column_name = col_name_match.group(1)

                rest = line[col_name_match.end():].strip()

                type_match = re.match(r'([a-zA-Z0-9_]+(?:\([^)]*\))?)', rest)
                if not type_match:
                    continue
                column_types = type_match.group(1)

                rest = rest[type_match.end():].strip()

                column_desc = ''
                comment_match = re.search(r'COMMENT\s+[\'\"]([^\'\"]+)[\'\"]', rest)
                if comment_match:
                    column_desc = comment_match.group(1)

                columns.append([
                    db_id,
                    'mysql',
                    table_name,
                    column_name,
                    column_types,
                    column_desc,
                    table_comment,
                    primary_key,
                    foreign_key
                ])
        return columns

    def get_existing_rows(self, csv_path):
        """获取已存在的行，用于去重"""
        existing = set()
        if os.path.exists(csv_path):
            with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                try:
                    next(reader)
                except StopIteration:
                    pass
                for row in reader:
                    if row:
                        existing.add(tuple(row))
        return existing

    def process_table(self, table_name, database=None, output_dir='.'):
        """处理单个表"""
        if '.' in table_name:
            db_id, actual_table_name = table_name.split('.', 1)
        else:
            db_id = database or self.db_config.get('database', '')
            actual_table_name = table_name

        ddl = self.get_ddl(actual_table_name, db_id)
        if not ddl:
            print(f"无法获取表 {table_name} 的DDL")
            return

        csv_path = os.path.join(output_dir, f'{db_id}.csv')

        existing_rows = self.get_existing_rows(csv_path)

        columns = self.parse_ddl(ddl, db_id)

        write_header = not os.path.exists(csv_path)
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(['db_id', 'db_type', 'table_name', 'column_name', 'column_types',
                                'column_descriptions', 'table_comment', 'primary_key', 'foreign_key'])

            for row in columns:
                row[2] = actual_table_name
                row_tuple = tuple(row)
                if row_tuple not in existing_rows:
                    writer.writerow(row)
                    existing_rows.add(row_tuple)

        print(f"处理完成: {table_name} -> {csv_path}")

    def process_tables(self, tables=None, database=None, output_dir='.'):
        """处理多个表"""
        if not tables:
            tables = self.get_table_list(database)

        for table in tables:
            self.process_table(table, database, output_dir)

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()


def main():
    """命令行入口 - 从环境变量读取配置"""
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': os.getenv('DB_NAME', ''),
        'charset': 'utf8mb4'
    }

    tables_str = os.getenv('DB_TABLES', '')
    tables = tables_str.split(',') if tables_str else None

    schema_util = DBSchemaUtil(db_config, tables)

    schema_util.test_connection()

    database = db_config['database']
    if tables is None:
        tables = schema_util.get_table_list(database)
        print(f"数据库 {database} 中的表: {tables}")
    else:
        print(f"指定处理的表: {tables}")

    output_dir = os.getenv('OUTPUT_DIR', '.')

    schema_util.process_tables(tables=tables, database=database, output_dir=output_dir)

    schema_util.close()
    print("处理完成！")


if __name__ == "__main__":
    main()
