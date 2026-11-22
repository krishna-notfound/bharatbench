/** Optional test account sent with a new run (memory only on the server). */
export interface TestAccount {
  login: string;
  password: string;
  note: string;
  offline_after_login: boolean;
}
