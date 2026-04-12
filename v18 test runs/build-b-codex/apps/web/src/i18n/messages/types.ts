export interface MessageDictionary {
  auth: {
    login: {
      clientGapBody: string;
      clientGapTitle: string;
      description: string;
      email: string;
      eyebrow: string;
      helper: string;
      invalid: string;
      password: string;
      submit: string;
      title: string;
      unavailable: string;
    };
  };
  common: {
    appName: string;
    close: string;
    closeMenu: string;
    comingSoon: string;
    loading: string;
    openMenu: string;
    previewMode: string;
    retry: string;
    signIn: string;
    unavailable: string;
  };
  errors: {
    clientUnavailable: string;
    email: string;
    maxLength: string;
    minLength: string;
    required: string;
  };
  nav: {
    login: string;
    projects: string;
    team: string;
  };
  projects: {
    description: string;
    emptyBody: string;
    emptyTitle: string;
    eyebrow: string;
    newProject: string;
    title: string;
  };
  shell: {
    currentLocale: string;
    eyebrow: string;
    language: string;
    logout: string;
    noSession: string;
    roleAdmin: string;
    roleMember: string;
    sessionMissing: string;
    sessionReady: string;
    subtitle: string;
    title: string;
    userMenu: string;
  };
  system: {
    errorBody: string;
    errorTitle: string;
  };
  team: {
    browseMembers: string;
    description: string;
    emptyBody: string;
    emptyTitle: string;
    eyebrow: string;
    title: string;
  };
}

type Join<K extends string, P extends string> = `${K}.${P}`;

type NestedKeys<T> = {
  [K in keyof T & string]: T[K] extends string
    ? K
    : T[K] extends Record<string, unknown>
      ? Join<K, NestedKeys<T[K]>>
      : never;
}[keyof T & string];

export type TranslationKey = NestedKeys<MessageDictionary>;
