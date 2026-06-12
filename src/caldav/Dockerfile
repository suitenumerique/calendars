# sabre/dav CalDAV Server
# Based on Debian with Apache and PHP. Pinned to 8.5 to match the
# scalingo-26 (Ubuntu 26.04) production stack, whose only PHP is 8.5.
FROM php:8.5-apache-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    libonig-dev \
    postgresql-client \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install PHP extensions. ``mbstring`` is mandatory: the
# CalendarSanitizerPlugin uses ``mb_strcut`` to truncate
# DESCRIPTION/SUMMARY/LOCATION on a UTF-8 boundary, and there is no
# safe fallback — without it a multi-byte truncation would emit
# invalid UTF-8 (or fatal).
RUN docker-php-ext-install pdo pdo_pgsql mbstring

# Install Composer
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# Create application directory
WORKDIR /var/www/sabredav

# Copy composer files and install dependencies from the lockfile.
# The post-install script (declared in composer.json) bumps SabreDAV's
# MAX_DATE constant — see bin/patch-sabredav-max-date.php for the why.
COPY composer.json composer.lock ./
COPY bin/ ./bin/
RUN composer install --no-dev --optimize-autoloader --no-interaction

# Copy server configuration
COPY server.php ./
COPY sabredav.conf /etc/apache2/sites-available/sabredav.conf
COPY init-database.sh /usr/local/bin/init-database.sh

# Copy SQL schema files for database initialization
COPY sql/ ./sql/

# Copy custom principal backend
COPY src/ ./src/

# Enable Apache modules and site
RUN a2enmod rewrite headers \
    && a2dissite 000-default \
    && a2ensite sabredav \
    && chmod +x /usr/local/bin/init-database.sh

# Configure PHP error logging to stderr for Docker logs
# This ensures all error_log() calls and PHP errors are visible in docker logs
# display_errors = Off prevents errors from appearing in HTTP responses (security/UX)
# but errors are still logged to stderr (Docker logs) via log_errors = On
RUN echo "log_errors = On" >> /usr/local/etc/php/conf.d/error-logging.ini \
    && echo "error_log = /proc/self/fd/2" >> /usr/local/etc/php/conf.d/error-logging.ini \
    && echo "display_errors = Off" >> /usr/local/etc/php/conf.d/error-logging.ini \
    && echo "display_startup_errors = Off" >> /usr/local/etc/php/conf.d/error-logging.ini \
    && echo "memory_limit = 512M" >> /usr/local/etc/php/conf.d/error-logging.ini

# Set permissions
RUN chown -R www-data:www-data /var/www/sabredav \
    && chmod -R 755 /var/www/sabredav

EXPOSE 80

CMD ["apache2-foreground"]
