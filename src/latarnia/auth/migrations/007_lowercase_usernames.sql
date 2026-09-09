-- P-0011: usernames are case insensitive.
--
-- Every write now goes through normalize_username() in auth/users.py, so the
-- plain UNIQUE on users.username is enough to enforce case-insensitive
-- uniqueness -- no CITEXT, no functional index. This migration folds the rows
-- that predate that change.
--
-- Rows whose usernames collide once lowercased cannot all keep their name. The
-- oldest row keeps the plain lowercase name; each newer row gets the lowest
-- free numeric suffix and a WARNING (surfaced by the notice handler in
-- auth/db.py). Renaming is safe: user_credentials, sessions, app_roles, and
-- machine_tokens all reference users.id, never the name.
--
-- Re-runnable: the DO block is a no-op once there are no collisions, the fold is
-- guarded by a WHERE, and the constraint is dropped before being added.

DO $$
DECLARE
    grp    RECORD;
    victim RECORD;
    base   TEXT;
    cand   TEXT;
    n      INTEGER;
BEGIN
    FOR grp IN
        SELECT lower(username) AS lname
        FROM users
        GROUP BY lower(username)
        HAVING COUNT(*) > 1
    LOOP
        -- left(..., 62) keeps `base || n` inside the 1-64 char contract that
        -- USERNAME_RE enforces on invite, even for a name using all 64 chars.
        base := left(grp.lname, 62);
        n := 1;

        -- OFFSET 1 skips the oldest row: it keeps grp.lname unchanged.
        FOR victim IN
            SELECT id, username
            FROM users
            WHERE lower(username) = grp.lname
            ORDER BY created_at, id
            OFFSET 1
        LOOP
            LOOP
                n := n + 1;
                cand := base || n::TEXT;
                -- Compare on lower(username) so a candidate cannot collide
                -- with a row that has not been folded yet.
                EXIT WHEN NOT EXISTS (
                    SELECT 1 FROM users WHERE lower(username) = cand
                );
            END LOOP;

            UPDATE users SET username = cand WHERE id = victim.id;
            RAISE WARNING
                'P-0011: renamed colliding username % -> % (user %)',
                victim.username, cand, victim.id;
        END LOOP;
    END LOOP;
END $$;

-- Safe against UNIQUE: the DO block above removed every case-variant collision.
UPDATE users SET username = lower(username) WHERE username <> lower(username);

-- Belt to normalize_username()'s braces: if a future code path ever bypasses
-- UserStore, the write fails loudly here instead of silently reintroducing a
-- case-sensitive duplicate.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_lowercase;
ALTER TABLE users ADD CONSTRAINT users_username_lowercase
    CHECK (username = lower(username));
