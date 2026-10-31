-- Run once in MySQL Workbench (connected as root) so the Sage container can read your data.
-- 1. Replace CHANGE_ME with a strong password and put the same value in .env.docker as DB_PASSWORD.
-- 2. Add or remove GRANT lines for the databases Sage should see.
CREATE USER IF NOT EXISTS 'sage_reader'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, SHOW VIEW ON `messy_employees`.* TO 'sage_reader'@'%';
GRANT SELECT, SHOW VIEW ON `co-pilot employees`.* TO 'sage_reader'@'%';
FLUSH PRIVILEGES;
