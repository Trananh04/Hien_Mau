-- Xem cấu trúc bảng (giống màn hình Design Table) trong pgAdmin Query Tool.
-- Cách dùng: bôi đen MỘT câu lệnh (cách 1 hoặc cách 2) rồi bấm F5. Không bôi đen thì pgAdmin chạy cả hai.

-- ===== CÁCH 1: xem MỘT bảng — chỉ cần đổi tên bảng ở dòng dưới =====
WITH bang AS (SELECT 'users' AS ten)
SELECT c.column_name                                   AS "Name",
       c.data_type                                     AS "Type",
       c.character_maximum_length                      AS "Length",
       col_description(('public.' || c.table_name)::regclass, c.ordinal_position) AS "Comment",
       c.column_default                                AS "Default",
       (c.is_nullable = 'NO')                          AS "Not Null",
       EXISTS (SELECT 1 FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage k
                 ON k.constraint_name = tc.constraint_name AND k.table_name = tc.table_name
               WHERE tc.table_name = c.table_name AND tc.constraint_type = 'PRIMARY KEY'
                 AND k.column_name = c.column_name)    AS "Primary Key",
       EXISTS (SELECT 1 FROM pg_index i
               JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
               WHERE i.indrelid = ('public.' || c.table_name)::regclass
                 AND i.indisunique AND i.indnatts = 1 AND i.indpred IS NULL
                 AND a.attname = c.column_name)        AS "UNIQUE",
       (c.is_identity = 'YES' OR COALESCE(c.column_default, '') LIKE 'nextval%') AS "Auto Increment",
       fk.ref                                          AS "Foreign Key"
FROM information_schema.columns c
LEFT JOIN LATERAL (
    SELECT ccu.table_name || '(' || ccu.column_name || ')' AS ref
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage k
      ON k.constraint_name = tc.constraint_name AND k.table_name = tc.table_name
    JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
    WHERE tc.table_name = c.table_name AND tc.constraint_type = 'FOREIGN KEY' AND k.column_name = c.column_name
    LIMIT 1) fk ON true
WHERE c.table_schema = 'public' AND c.table_name = (SELECT ten FROM bang)
ORDER BY c.ordinal_position;


-- ===== CÁCH 2: xem TẤT CẢ 23 bảng của dự án cùng lúc (bỏ qua bảng hệ thống của Django) =====
SELECT c.table_name                                    AS "Table",
       c.column_name                                   AS "Name",
       c.data_type                                     AS "Type",
       c.character_maximum_length                      AS "Length",
       col_description(('public.' || c.table_name)::regclass, c.ordinal_position) AS "Comment",
       c.column_default                                AS "Default",
       (c.is_nullable = 'NO')                          AS "Not Null",
       EXISTS (SELECT 1 FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage k
                 ON k.constraint_name = tc.constraint_name AND k.table_name = tc.table_name
               WHERE tc.table_name = c.table_name AND tc.constraint_type = 'PRIMARY KEY'
                 AND k.column_name = c.column_name)    AS "Primary Key",
       EXISTS (SELECT 1 FROM pg_index i
               JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
               WHERE i.indrelid = ('public.' || c.table_name)::regclass
                 AND i.indisunique AND i.indnatts = 1 AND i.indpred IS NULL
                 AND a.attname = c.column_name)        AS "UNIQUE",
       (c.is_identity = 'YES' OR COALESCE(c.column_default, '') LIKE 'nextval%') AS "Auto Increment",
       fk.ref                                          AS "Foreign Key"
FROM information_schema.columns c
LEFT JOIN LATERAL (
    SELECT ccu.table_name || '(' || ccu.column_name || ')' AS ref
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage k
      ON k.constraint_name = tc.constraint_name AND k.table_name = tc.table_name
    JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
    WHERE tc.table_name = c.table_name AND tc.constraint_type = 'FOREIGN KEY' AND k.column_name = c.column_name
    LIMIT 1) fk ON true
WHERE c.table_schema = 'public' AND c.table_name NOT LIKE 'django\_%' AND c.table_name NOT LIKE 'auth\_group%' AND c.table_name <> 'auth_permission'
ORDER BY c.table_name, c.ordinal_position;
