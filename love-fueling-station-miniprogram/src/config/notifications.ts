/**
 * Fill this with the one-time subscription template ID after the mini program
 * has passed certification. The value must match the Cloud Function env var
 * SUBSCRIBE_TEMPLATE_ID. Keeping it empty makes the entry safely unavailable.
 */
export const partnerNotificationTemplateId = '';

export const partnerNotificationsConfigured = partnerNotificationTemplateId.trim().length > 0;
