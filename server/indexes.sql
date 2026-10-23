
CREATE INDEX IF NOT EXISTS idx_images_owner ON images(owner_id);
CREATE INDEX IF NOT EXISTS idx_images_tag ON images(tag);
CREATE INDEX IF NOT EXISTS idx_images_cursor ON images(created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_images_owner_cursor ON images(owner_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_images_tag_cursor ON images(tag,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
