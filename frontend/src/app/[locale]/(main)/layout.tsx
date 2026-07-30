import { ChatClientRoot } from "@/components/features/chat/routes/chat-client-root";

interface MainLayoutProps {
  children: React.ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return <ChatClientRoot>{children}</ChatClientRoot>;
}
