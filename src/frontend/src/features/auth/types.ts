export interface Organization {
  id: string;
  name: string;
}

/**
 * Represents user retrieved from the API.
 * @interface User
 * @property {string} id - The id of the user.
 * @property {string} email - The email of the user.
 * @property {string | null} language - The saved language of the user, or null.
 * @property {boolean} can_access - Whether the user can access the app.
 * @property {boolean} can_admin - Whether the user can administer resources.
 * @property {Organization} organization - The user's organization.
 */
export interface User {
  id: string;
  email: string;
  full_name?: string;
  language: string | null;
  can_access: boolean;
  can_admin: boolean;
  organization?: Organization;
}
