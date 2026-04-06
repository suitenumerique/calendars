CREATE TABLE principals (
    id SERIAL NOT NULL,
    uri VARCHAR(200) NOT NULL,
    email VARCHAR(255),
    displayname VARCHAR(255),
    calendar_user_type VARCHAR(20) DEFAULT 'INDIVIDUAL',
    org_id VARCHAR(200)
);

ALTER TABLE ONLY principals
    ADD CONSTRAINT principals_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX principals_ukey
    ON principals USING btree (uri);

CREATE INDEX idx_principals_org_id
    ON principals (org_id)
    WHERE org_id IS NOT NULL;

CREATE INDEX idx_principals_email
    ON principals (email);

CREATE INDEX idx_principals_cutype
    ON principals (calendar_user_type)
    WHERE calendar_user_type IN ('ROOM', 'RESOURCE');

CREATE TABLE groupmembers (
    id SERIAL NOT NULL,
    principal_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL
);

ALTER TABLE ONLY groupmembers
    ADD CONSTRAINT groupmembers_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX groupmembers_ukey
    ON groupmembers USING btree (principal_id, member_id);

-- No seed data. Principals are auto-created by PrincipalBackend on first
-- CalDAV access (without calendars). Calendars are created explicitly via
-- POST /api/v1.0/setup/ → POST /internal-api/calendars/.
--
-- calendar-user-address-set is derived at runtime by PrincipalBackend
-- from calendarinstances shares to MAILBOX principals. No separate table needed.
