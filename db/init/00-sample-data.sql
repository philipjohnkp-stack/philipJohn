-- Runs once, on the first start of an empty MySQL volume.
CREATE TABLE IF NOT EXISTS employees (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    department VARCHAR(50) NOT NULL,
    salary DECIMAL(10, 2) NOT NULL,
    hire_date DATE NOT NULL
);

INSERT INTO employees (name, department, salary, hire_date) VALUES
    ('Ava Patel', 'Sales', 62000, '2021-03-15'),
    ('Liam Chen', 'Engineering', 98000, '2019-07-01'),
    ('Noah Singh', 'Engineering', 87000, '2022-01-10'),
    ('Mia Johnson', 'Marketing', 58000, '2020-11-23'),
    ('Ethan Brown', 'Sales', 71000, '2018-05-30'),
    ('Sofia Garcia', 'Finance', 76000, '2023-02-14');
