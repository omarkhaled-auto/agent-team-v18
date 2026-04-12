import type { MessageDictionary } from '@/i18n/messages/types';

export const enMessages = {
  auth: {
    login: {
      clientGapBody:
        'Wave C generated duplicate client exports, so this form can validate but it cannot submit a typed request yet.',
      clientGapTitle: 'Typed API client unavailable',
      description:
        'Keep the workspace moving with a compact operating view built for project intake, review, and delivery.',
      email: 'Work email',
      eyebrow: 'Operator sign-in',
      helper: 'Use your assigned email and password once the generated client is repaired upstream.',
      invalid: 'The credentials were rejected.',
      password: 'Password',
      submit: 'Sign In',
      title: 'Bring the next project into focus.',
      unavailable: 'Authentication is temporarily unavailable.',
    },
  },
  common: {
    appName: 'Signal Desk',
    close: 'Close',
    closeMenu: 'Close navigation',
    comingSoon: 'This view is ready for the next milestone.',
    loading: 'Loading workspace…',
    openMenu: 'Open navigation',
    previewMode: 'Preview mode',
    retry: 'Retry',
    signIn: 'Sign In',
    unavailable: 'Service unavailable',
  },
  errors: {
    clientUnavailable: 'The generated client is invalid and blocked the login request.',
    email: 'Enter a valid email address.',
    maxLength: 'This value is too long.',
    minLength: 'This value is too short.',
    required: 'This field is required.',
  },
  nav: {
    login: 'Login',
    projects: 'Projects',
    team: 'Team',
  },
  projects: {
    description: 'A dense project rail with room for intake, ownership, and task flow once the typed client is fixed.',
    emptyBody: 'Project records will appear here after typed project queries are restored.',
    emptyTitle: 'No projects available in the scaffold yet.',
    eyebrow: 'Project board',
    newProject: 'Create Project',
    title: 'Project operations',
  },
  shell: {
    currentLocale: 'Current locale',
    eyebrow: 'Workspace shell',
    language: 'Language',
    logout: 'Log Out',
    noSession: 'No active session',
    roleAdmin: 'Administrator',
    roleMember: 'Member',
    sessionMissing: 'No JWT session is stored in this browser yet.',
    sessionReady: 'Session status',
    subtitle: 'Industrial navigation, translation-ready copy, and auth state wiring.',
    title: 'Control Room',
    userMenu: 'User menu',
  },
  system: {
    errorBody: 'The route hit an unexpected error. Reset the boundary and continue from the current locale.',
    errorTitle: 'The workspace hit a fault.',
  },
  team: {
    browseMembers: 'Browse Team',
    description: 'A multilingual directory shell for ownership, assignees, and reporting lines.',
    emptyBody: 'Member cards will populate here after the typed users client is regenerated.',
    emptyTitle: 'No team data can be loaded from the generated client.',
    eyebrow: 'Team directory',
    title: 'Team operations',
  },
} satisfies MessageDictionary;
