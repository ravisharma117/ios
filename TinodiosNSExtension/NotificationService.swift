//
//  NotificationService.swift
//  TinodiosNSExtension
//
//  Copyright © 2019-2022 Tinode. All rights reserved.
//

import UserNotifications
import TinodeSDK
import TinodiosDB

class NotificationService: UNNotificationServiceExtension {

    var contentHandler: ((UNNotificationContent) -> Void)?
    var bestAttemptContent: UNMutableNotificationContent?

    let log = TinodeSDK.Log(subsystem: BaseDb.kBundleId)

    // GEIA: fixed text of every visible notification.
    static let kGeiaTitle = "Geia Messaging"
    static let kGeiaBody = "New message received"

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        self.contentHandler = contentHandler
        self.bestAttemptContent = (request.content.mutableCopy() as? UNMutableNotificationContent)

        // GEIA: content-free notifications. Every visible notification (message or new chat) reads
        // "Geia Messaging" / "New message received": no sender, no chat name, no message text.
        // Nothing is looked up in the local database or fetched from the server, and the text is fixed
        // in code, so it cannot depend on what the push carries. Silent pushes (read, deleted, calls)
        // are passed through unchanged.
        //

        if let bestAttemptContent = bestAttemptContent {
            let action = bestAttemptContent.userInfo["what"] as? String ?? "msg"

            guard ["msg", "sub"].contains(action) else {
                // Not handling it here.
                self.contentHandler!(bestAttemptContent)
                return
            }

            bestAttemptContent.title = NotificationService.kGeiaTitle
            bestAttemptContent.subtitle = ""
            bestAttemptContent.body = NotificationService.kGeiaBody
            self.contentHandler!(bestAttemptContent)
        } else {
            self.contentHandler!(request.content)
        }
    }

    override func serviceExtensionTimeWillExpire() {
        // 30 seconds.
        if let contentHandler = contentHandler, let bestAttemptContent = bestAttemptContent {
            contentHandler(bestAttemptContent)
        }
    }

}
