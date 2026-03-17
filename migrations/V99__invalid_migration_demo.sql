-- This migration is intentionally broken for failure simulation.
-- It should only be run explicitly in the failure demo.
ALTER TABLE users
    ADDD COLUMN broken_column VARCHAR(50);
