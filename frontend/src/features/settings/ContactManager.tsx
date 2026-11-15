import type { ComponentProps } from "react";
import {ContactsPage} from "../contacts/ContactsPage";
export function ContactManager(props:ComponentProps<typeof ContactsPage>){return <ContactsPage {...props} management/>;}
