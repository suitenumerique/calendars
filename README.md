<p align="center">
  <a href="https://github.com/suitenumerique/calendars">
    <img alt="Calendars banner" src="/docs/assets/banner-calendars.png" width="100%" />
  </a>
</p>
<p align="center">
  <img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/suitenumerique/calendars"/>
  <img alt="GitHub closed issues" src="https://img.shields.io/github/issues-closed/suitenumerique/calendars"/>
  <a href="https://github.com/suitenumerique/calendars/blob/main/LICENSE">
    <img alt="GitHub closed issues" src="https://img.shields.io/github/license/suitenumerique/calendars"/>
  </a>    
</p>

<p align="center">
  <a href="https://matrix.to/#/#calendars-official:matrix.org">
    Chat on Matrix
  </a> - <a href="/docs/">
    Documentation
  </a> - <a href="#getting-started-">
    Getting started
  </a> - <a href="mailto:contact@suite.anct.gouv.fr">
    Reach out
  </a>
</p>

# Calendars
A modern, open-source calendar application for managing events and schedules.

<img src="/docs/assets/calendars-UI.png" width="100%" align="center"/>


## Why use Calendars ❓
Calendars empowers teams to manage events and schedules while maintaining full control over their data through a user-friendly, open-source platform.

### Manage Events
- 📅 Create and manage events and schedules
- 🌐 Access your calendar from anywhere with our web-based interface

### Organize
- 📂 Organized calendar structure with intuitive navigation

### Collaborate
- 🤝 Share calendars with your team members  
- 👥 Granular access control to ensure your information is secure and only shared with the right people
- 🏢 Create workspaces to organize team collaboration

### Self-host
*   🚀 Easy to install, scalable and secure calendar solution

## Getting started 🔧

### Prerequisite

Make sure you have a recent version of Docker and [Docker
Compose](https://docs.docker.com/compose/install) installed on your laptop:

```bash
$ docker -v
  Docker version 27.x

$ docker compose version
  Docker Compose version v2.x
```

> ⚠️ You may need to run the following commands with `sudo` but this can be
> avoided by assigning your user to the `docker` group.

### Bootstrap project

The easiest way to start working on the project is to use GNU Make:

```bash
$ make bootstrap
```

This command builds the containers, installs dependencies, and runs database
migrations. It's a good idea to use this command each time you are pulling
code from the project repository to avoid dependency-related or
migration-related issues.

Your Docker services should now be up and running! 🎉

You can access the project by going to <http://localhost:8930>.

You will be prompted to log in. The following test users are
pre-configured in Keycloak (password = username prefix):

| Email | Password | Org domain |
|---|---|---|
| `user1@example.local` | `user1` | `example.local` |
| `user2@example.local` | `user2` | `example.local` |
| `user3@example.local` | `user3` | `example.local` |
| `user1.2@example2.local` | `user1.2` | `example2.local` |
| `user2.2@example2.local` | `user2.2` | `example2.local` |

Users sharing the same domain are placed in the same organization
automatically on first login. Use users from different domains
(`example.local` vs `example2.local`) to test cross-org isolation.

Note that if you need to run them afterward, you can use the eponym Make rule:

```bash
$ make start
```

You can check all available Make rules using:

```bash
$ make help
```

⚠️ For frontend developers, it is often better to run the frontend in development mode locally.

First, install the frontend dependencies:

```bash
$ make install-front
```

Then start the backend services:

```bash
$ make start-back
```

And run the frontend locally in development mode:

```bash
$ cd src/frontend/apps/calendars && npm run dev
```

### Django admin

You can access the Django admin site at
[http://localhost:8931/admin](http://localhost:8931/admin).

You first need to create a superuser account:

```bash
$ make superuser
```

You can then login with sub `admin@example.com` and password `admin`.


## Feedback 🙋‍♂️🙋‍♀️

We'd love to hear your thoughts and hear about your experiments, so come and say hi on [Matrix](https://matrix.to/#/#calendars-official:matrix.org).

## Contributing 🙌

This project is intended to be community-driven, so please, do not hesitate to get in touch if you have any question related to our implementation or design
decisions.

## License 📝

This work is released under the MIT License (see [LICENSE](./LICENSE)).

While Calendars is a public driven initiative our licence choice is an invitation for private sector actors to use, sell and contribute to the project. 

## Credits ❤️

Calendars is built on top of [Django REST Framework](https://www.django-rest-framework.org/), [Next.js](https://nextjs.org/) and [SabreDAV](https://sabre.io/dav/). We thank the contributors of all these projects for their awesome work!
