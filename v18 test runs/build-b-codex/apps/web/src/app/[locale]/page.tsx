import { redirect } from 'next/navigation';

interface LocaleIndexPageProps {
  params: {
    locale: string;
  };
}

export default function LocaleIndexPage({ params }: LocaleIndexPageProps): never {
  redirect(`/${params.locale}/projects`);
}
