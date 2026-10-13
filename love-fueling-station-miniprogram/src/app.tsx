import { PropsWithChildren } from 'react';
import { CloudSyncBridge } from './components/CloudSyncBridge';
import { RelationshipProvider } from './store/relationship-store';
import './app.scss';

export default function App({ children }: PropsWithChildren) {
  return <RelationshipProvider><CloudSyncBridge>{children}</CloudSyncBridge></RelationshipProvider>;
}
