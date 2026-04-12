import type { MessageDictionary } from '@/i18n/messages/types';

export const idMessages = {
  auth: {
    login: {
      clientGapBody:
        'Wave C menghasilkan ekspor klien yang duplikat, jadi formulir ini bisa memvalidasi input tetapi belum bisa mengirim permintaan bertipe dengan aman.',
      clientGapTitle: 'Klien API bertipe belum tersedia',
      description:
        'Pertahankan ritme kerja dengan tampilan operasi ringkas untuk intake proyek, peninjauan, dan pengiriman.',
      email: 'Email kerja',
      eyebrow: 'Masuk operator',
      helper: 'Gunakan email dan kata sandi yang ditetapkan setelah klien hasil generate diperbaiki di hulu.',
      invalid: 'Kredensial ditolak.',
      password: 'Kata sandi',
      submit: 'Masuk',
      title: 'Arahkan proyek berikutnya ke fokus kerja.',
      unavailable: 'Autentikasi sementara tidak tersedia.',
    },
  },
  common: {
    appName: 'Signal Desk',
    close: 'Tutup',
    closeMenu: 'Tutup navigasi',
    comingSoon: 'Tampilan ini siap untuk milestone berikutnya.',
    loading: 'Memuat ruang kerja…',
    openMenu: 'Buka navigasi',
    previewMode: 'Mode pratinjau',
    retry: 'Coba lagi',
    signIn: 'Masuk',
    unavailable: 'Layanan tidak tersedia',
  },
  errors: {
    clientUnavailable: 'Klien hasil generate tidak valid dan memblokir permintaan login.',
    email: 'Masukkan alamat email yang valid.',
    maxLength: 'Nilai ini terlalu panjang.',
    minLength: 'Nilai ini terlalu pendek.',
    required: 'Kolom ini wajib diisi.',
  },
  nav: {
    login: 'Login',
    projects: 'Proyek',
    team: 'Tim',
  },
  projects: {
    description: 'Rel proyek padat dengan ruang untuk intake, kepemilikan, dan alur tugas saat klien bertipe sudah pulih.',
    emptyBody: 'Data proyek akan muncul di sini setelah kueri proyek bertipe tersedia lagi.',
    emptyTitle: 'Belum ada proyek yang bisa ditampilkan pada scaffold ini.',
    eyebrow: 'Papan proyek',
    newProject: 'Buat Proyek',
    title: 'Operasi proyek',
  },
  shell: {
    currentLocale: 'Lokal aktif',
    eyebrow: 'Shell ruang kerja',
    language: 'Bahasa',
    logout: 'Keluar',
    noSession: 'Tidak ada sesi aktif',
    roleAdmin: 'Administrator',
    roleMember: 'Anggota',
    sessionMissing: 'Belum ada sesi JWT yang tersimpan di browser ini.',
    sessionReady: 'Status sesi',
    subtitle: 'Navigasi industrial, salinan siap terjemah, dan wiring status autentikasi.',
    title: 'Ruang Kendali',
    userMenu: 'Menu pengguna',
  },
  system: {
    errorBody: 'Rute mengalami kesalahan tak terduga. Reset boundary lalu lanjutkan dari locale saat ini.',
    errorTitle: 'Ruang kerja mengalami gangguan.',
  },
  team: {
    browseMembers: 'Lihat Tim',
    description: 'Shell direktori multibahasa untuk pemilik, assignee, dan garis pelaporan.',
    emptyBody: 'Kartu anggota akan muncul di sini setelah klien pengguna bertipe dibuat ulang.',
    emptyTitle: 'Data tim belum bisa dimuat dari klien hasil generate.',
    eyebrow: 'Direktori tim',
    title: 'Operasi tim',
  },
} satisfies MessageDictionary;
