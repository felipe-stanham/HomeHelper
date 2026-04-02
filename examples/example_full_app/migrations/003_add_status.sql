-- Add status column to items
ALTER TABLE items ADD COLUMN status VARCHAR(20) DEFAULT 'active';
CREATE INDEX idx_items_status ON items(status);
