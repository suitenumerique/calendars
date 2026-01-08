# DAViCal CalDAV Server
# Based on Debian with Apache and PHP
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    apache2 \
    libapache2-mod-php \
    php-pgsql \
    php-xml \
    php-curl \
    php-imap \
    php-ldap \
    davical \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Enable required Apache modules
RUN a2enmod rewrite

# Copy Apache configuration
COPY davical.conf /etc/apache2/sites-available/davical.conf
RUN a2dissite 000-default && a2ensite davical

# Copy DAViCal configuration
COPY config.php /etc/davical/config.php

# Copy and setup entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set permissions
RUN chown -R www-data:www-data /var/log/apache2

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
