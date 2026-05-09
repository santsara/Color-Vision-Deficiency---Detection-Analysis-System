SELECT * FROM users;
SELECT * FROM test_results;
UPDATE test_results
SET test_type = 'D-15'
WHERE test_type = 'mosaic';


CREATE VIEW IF NOT EXISTS user_test_records AS
SELECT 
    test_results.id AS Test_ID,
    IFNULL(users.name, 'Guest') AS Patient_Name,
    IFNULL(users.email, 'No Email (Guest)') AS Email,
    test_results.test_type AS Test_Type,
    test_results.score AS Score,
    test_results.total_questions AS Total,
    test_results.diagnosis AS Diagnosis,
    test_results.timestamp AS Time_Taken
FROM test_results
LEFT JOIN users ON test_results.user_id = users.id
ORDER BY test_results.timestamp DESC;

SELECT * FROM test_results

UPDATE test_results
SET id = id - 2
WHERE id > 13;

SELECT * FROM user_test_records;

DELETE FROM test_results
WHERE id = 14;

UPDATE test_results 
SET diagnosis = REPLACE(diagnosis, 'undetermined', 'unclear');

-- This forces the hidden counter to perfectly match your highest current ID
UPDATE sqlite_sequence 
SET seq = (SELECT MAX(id) FROM test_results) 
WHERE name = 'test_results';