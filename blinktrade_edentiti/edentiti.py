#!/usr/bin/env python

import argparse
import urllib
import json
from urlparse import urlparse

import datetime
from time import mktime

from pysimplesoap.client import SoapClient

from twisted.internet import reactor, ssl
from twisted.web.client import getPage
from autobahn.twisted.websocket import WebSocketClientProtocol, WebSocketClientFactory

from pyblinktrade.message_builder import MessageBuilder
from pyblinktrade.message import JsonMessage


def get_verification_data(all_verification_data, key):
  value = None
  for data in reversed(all_verification_data):
    if key in data:
      value=data[key]
      break
  return value


class BtcWithdrawalProtocol(WebSocketClientProtocol):
  def onConnect(self, response):
    print("Server connected: {0}".format(response.peer))

  def sendJSON(self, json_message):
    message = json.dumps(json_message).encode('utf8')
    if self.factory.verbose:
      print 'tx:',message
    self.sendMessage(message)

  def onOpen(self):
    def sendTestRequest():
      self.sendJSON( MessageBuilder.testRequestMessage() )
      self.factory.reactor.callLater(60, sendTestRequest)

    sendTestRequest()

    self.sendJSON( MessageBuilder.login(  self.factory.blintrade_user, self.factory.blintrade_password ) )

  def onMessage(self, payload, isBinary):
    if isBinary:
      print("Binary message received: {0} bytes".format(len(payload)))
      reactor.stop()
      return

    if self.factory.verbose:
      print 'rx:',payload

    msg = JsonMessage(payload.decode('utf8'))
    if msg.isHeartbeat():
      return

    if msg.isUserResponse(): # login response
      if msg.get('UserStatus') != 1:
        reactor.stop()
        raise RuntimeError('Wrong login')

      profile = msg.get('Profile')
      if profile['Type'] != 'BROKER':
        reactor.stop()
        raise RuntimeError('It is not a brokerage account')

      self.factory.broker_username = msg.get('Username')
      self.factory.broker_id = msg.get('UserID')
      self.factory.profile = profile
      return


    if msg.isVerifyCustomerRefresh():
      broker_id         = msg.get('BrokerID')
      if broker_id != self.factory.broker_id:
        return # received a message from a different broker

      verified          = msg.get('Verified')
      if verified != 1:
        return

      user_id           = msg.get('ClientID')
      username          = msg.get('Username')
      verification_data = msg.get('VerificationData')
      if verification_data:
        verification_data = json.loads(verification_data)

      edentiti_status = get_verification_data(verification_data, 'edentiti_status')
      if edentiti_status == "IN_PROGRESS":
        return

      street_address = get_verification_data(verification_data, 'address')['street1']
      flat_number = ''
      if '/' in street_address:
        flat_number = street_address[:street_address.find('/') ]
        street_address = street_address[street_address.find('/')+1: ]

      street_address_parts = street_address.split(" ")
      street_type = ""
      if len(street_address_parts) > 1:
        street_type = street_address_parts[-1]
        street_address = ' '.join(street_address_parts[:-1])

      street_address_parts = street_address.split(" ")
      street_number = ""
      if street_address_parts and street_address_parts[0].isdigit():
        street_number = street_address_parts[0]
        street_address = ' '.join(street_address_parts[1:])

      street_name = street_address

      try:
        res = self.factory.wsdl_client.registerUser(
            customerId=self.factory.edentiti_customer_id,
            password=self.factory.edentiti_password,
            ruleId='default',
            name={
              'givenName': get_verification_data(verification_data, 'name')['first'],
              'middleNames': get_verification_data(verification_data, 'name')['middle'],
              'surname': get_verification_data(verification_data, 'name')['last']
            },
            currentResidentialAddress={
              'country':get_verification_data(verification_data, 'address')['country_code'],
              'flatNumber': flat_number,
              'postcode': get_verification_data(verification_data, 'address')['postal_code'],
              'propertyName':'',
              'state':get_verification_data(verification_data, 'address')['state'],
              'streetName':street_name,
              'streetNumber': street_number ,
              'streetType': street_type.upper(),
              'suburb':get_verification_data(verification_data, 'address')['city']
            },
            homePhone=get_verification_data(verification_data, 'phone_number'),
            dob=datetime.datetime.strptime( get_verification_data(verification_data, 'date_of_birth') ,"%Y-%m-%d"))

        dt = datetime.datetime.now()
        createdAt = int(mktime(dt.timetuple()) + dt.microsecond/1000000.0)
        edentiti_verification_data = {
          "service_provider":"edentiti",
          "edentiti_status": res['return']['outcome'],
          "id": res['return']['transactionId'],
          "user_id": res['return']['userId'],
          "status": res['return']['outcome'],
          "created_at": createdAt,
          "updated_at": createdAt
        }
        if res['return']['outcome'] == "IN_PROGRESS":
          edentiti_verification_data["status"] = "progress"
          verified = 2

        if edentiti_verification_data["status"] == "valid":
          verified = 3

        self.sendJSON( MessageBuilder.verifyCustomer(user_id, verified, json.dumps(edentiti_verification_data)))

      except Exception:
        pass

  def onClose(self, wasClean, code, reason):
    print("WebSocket connection closed: {0}".format(reason))


def main():
  parser = argparse.ArgumentParser(description="Validates peoples identity using edentiti (green id) identity provider")
  parser.add_argument('-b', "--blinktrade_websocket_url", action="store", dest="blintrade_webscoket_url", help='Blinktrade Websocket Url', type=str)
  parser.add_argument('-u', "--blinktrade_username", action="store", dest="blintrade_user",     help='Blinktrade User', type=str)
  parser.add_argument('-p', "--blinktrade_password", action="store", dest="blintrade_password",  help='Blinktrade Password', type=str)
  parser.add_argument('-c', "--customer_id", action="store", dest="edentiti_customer_id",  help='Edentiti Web service password', type=str)
  parser.add_argument('-P', "--password", action="store", dest="edentiti_password",  help='Edentiti Web service password', type=str)
  parser.add_argument('-v', "--verbose", action="store_true", default=False, dest="verbose",  help='Verbose')
  parser.add_argument('-t', "--test", action="store_true", default=False, dest="test",  help='Verbose')

  test_wsdl = 'https://test.edentiti.com/Registrations-Registrations/VerificationServicesPassword?wsdl'
  production_wsdl = 'https://www.edentiti.com/Registrations-Registrations/VerificationServicesPassword?wsdl'

  arguments = parser.parse_args()

  wsdl = production_wsdl
  if arguments.test:
    wsdl = test_wsdl
  wsdl_client = SoapClient( wsdl=wsdl, soap_ns="soapenv", ns="ns1", trace=True)

  blinktrade_port = 443
  should_connect_on_ssl = True
  blinktrade_url = urlparse(arguments.blintrade_webscoket_url)
  if blinktrade_url.port is None and blinktrade_url.scheme == 'ws':
    should_connect_on_ssl = False
    blinktrade_port = 80

  factory = WebSocketClientFactory(blinktrade_url.geturl())
  factory.blintrade_user = arguments.blintrade_user
  factory.blintrade_password = arguments.blintrade_password
  factory.wsdl_client = wsdl_client
  factory.edentiti_customer_id = arguments.edentiti_customer_id
  factory.edentiti_password = arguments.edentiti_password
  factory.verbose = arguments.verbose

  factory.protocol = BtcWithdrawalProtocol
  if should_connect_on_ssl:
    reactor.connectSSL( blinktrade_url.netloc ,  blinktrade_port , factory, ssl.ClientContextFactory() )
  else:
    reactor.connectTCP(blinktrade_url.netloc ,  blinktrade_port , factory )

  reactor.run()


if __name__ == '__main__':
  main()
