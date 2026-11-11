import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { MutationConfirmationHost } from './ConfirmDialog';
import './styles.css';
import './dashboard.css';
import './catalog.css';
import './products.css';
import './overview.css';
import './overview-flow.css';
import './inventory.css';
import './purchases.css';
import './po-client.css';
import './pos.css';
import './pos-cart-quantity.css';
import './reports.css';
import './customers.css';
import './suppliers.css';
import './expenses.css';
import './account.css';
import './users.css';
import './settings.css';
import './file-actions.css';
import './staff.css';
import './staff-table.css';
import './staff-attendance.css';
import './notifications.css';
import './landing.css';
import './account-entry.css';
import './account-menu.css';
import './popups.css';
import './admin-governance.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <>
      <MutationConfirmationHost />
      <App />
    </>
  </React.StrictMode>,
);
