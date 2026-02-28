import React from 'react';
import { Route } from 'react-router-dom';

import { VoucherTerminal } from '@/components/VouchTerminal';

export const vouchRoute = <Route path="/vouch/:prospectId" element={<VoucherTerminal />} />;
