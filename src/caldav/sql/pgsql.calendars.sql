CREATE TABLE calendarobjects (
    id SERIAL NOT NULL,
    calendardata BYTEA,
    uri VARCHAR(200),
    calendarid INTEGER NOT NULL,
    lastmodified BIGINT,
    etag VARCHAR(32),
    size INTEGER NOT NULL,
    componenttype VARCHAR(8),
    firstoccurence BIGINT,
    lastoccurence BIGINT,
    uid VARCHAR(200),
    channel_id UUID,
    created_by VARCHAR(255),
    modified_by VARCHAR(255),
    created_at BIGINT,
    modified_by_at BIGINT
);

ALTER TABLE ONLY calendarobjects
    ADD CONSTRAINT calendarobjects_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX calendarobjects_ukey
    ON calendarobjects USING btree (calendarid, uri);

CREATE INDEX idx_calendarobjects_channel_id
    ON calendarobjects USING btree (channel_id);

CREATE INDEX idx_calendarobjects_created_by
    ON calendarobjects USING btree (created_by);


CREATE TABLE calendars (
    id SERIAL NOT NULL,
    synctoken INTEGER NOT NULL DEFAULT 1,
    components VARCHAR(21)
);

ALTER TABLE ONLY calendars
    ADD CONSTRAINT calendars_pkey PRIMARY KEY (id);


CREATE TABLE calendarinstances (
    id SERIAL NOT NULL,
    calendarid INTEGER NOT NULL,
    principaluri VARCHAR(255),
    access SMALLINT NOT NULL DEFAULT '1', -- '1 = owner, 2 = read, 3 = readwrite'
    displayname VARCHAR(255),
    uri VARCHAR(200),
    description TEXT,
    calendarorder INTEGER NOT NULL DEFAULT 0,
    calendarcolor VARCHAR(10),
    timezone TEXT,
    transparent SMALLINT NOT NULL DEFAULT '0',
    share_href VARCHAR(255),
    share_displayname VARCHAR(255),
    share_invitestatus SMALLINT NOT NULL DEFAULT '2' --  '1 = noresponse, 2 = accepted, 3 = declined, 4 = invalid'
);

ALTER TABLE ONLY calendarinstances
    ADD CONSTRAINT calendarinstances_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX calendarinstances_principaluri_uri
    ON calendarinstances USING btree (principaluri, uri);


CREATE UNIQUE INDEX calendarinstances_principaluri_calendarid
    ON calendarinstances USING btree (principaluri, calendarid);

-- Note: The original SabreDAV schema has a unique index on (principaluri, share_href),
-- but this prevents sharing multiple calendars with the same user.
-- We use a non-unique index instead for query performance.
CREATE INDEX calendarinstances_principaluri_share_href
    ON calendarinstances USING btree (principaluri, share_href);

CREATE TABLE calendarsubscriptions (
    id SERIAL NOT NULL,
    uri VARCHAR(200) NOT NULL,
    principaluri VARCHAR(255) NOT NULL,
    source TEXT,
    displayname VARCHAR(255),
    refreshrate VARCHAR(10),
    calendarorder INTEGER NOT NULL DEFAULT 0,
    calendarcolor VARCHAR(10),
    striptodos SMALLINT NULL,
    stripalarms SMALLINT NULL,
    stripattachments SMALLINT NULL,
    lastmodified BIGINT
);

ALTER TABLE ONLY calendarsubscriptions
    ADD CONSTRAINT calendarsubscriptions_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX calendarsubscriptions_ukey
    ON calendarsubscriptions USING btree (principaluri, uri);

CREATE TABLE calendarchanges (
    id SERIAL NOT NULL,
    uri VARCHAR(200) NOT NULL,
    synctoken INTEGER NOT NULL,
    calendarid INTEGER NOT NULL,
    operation SMALLINT NOT NULL DEFAULT 0
);

ALTER TABLE ONLY calendarchanges
    ADD CONSTRAINT calendarchanges_pkey PRIMARY KEY (id);

CREATE INDEX calendarchanges_calendarid_synctoken_ix
    ON calendarchanges USING btree (calendarid, synctoken);

CREATE TABLE schedulingobjects (
    id SERIAL NOT NULL,
    principaluri VARCHAR(255),
    calendardata BYTEA,
    uri VARCHAR(200),
    lastmodified BIGINT,
    etag VARCHAR(32),
    size INTEGER NOT NULL
);

ALTER TABLE ONLY schedulingobjects
    ADD CONSTRAINT schedulingobjects_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX schedulingobjects_ukey
    ON schedulingobjects USING btree (principaluri, uri);

CREATE INDEX schedulingobjects_principaluri_ix
    ON schedulingobjects USING btree (principaluri);
