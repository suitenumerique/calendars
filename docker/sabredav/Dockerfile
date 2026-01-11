# sabre/dav CalDAV Server
# Based on Debian with Apache and PHP
FROM php:8.2-apache-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    postgresql-client \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install PHP extensions
RUN docker-php-ext-install pdo pdo_pgsql

# Install Composer
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# Create application directory
WORKDIR /var/www/sabredav

# Copy composer files
COPY composer.json ./

# Install sabre/dav and dependencies
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

# Set permissions
RUN chown -R www-data:www-data /var/www/sabredav \
    && chmod -R 755 /var/www/sabredav

EXPOSE 80

CMD ["apache2-foreground"]
