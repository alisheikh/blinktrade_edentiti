#!/usr/bin/env python

import argparse
import urllib
import json
from urlparse import urlparse

import datetime
from pysimplesoap.client import SoapClient

from twisted.internet import reactor, ssl
from twisted.web.client import getPage
from autobahn.twisted.websocket import WebSocketClientProtocol, WebSocketClientFactory

from pyblinktrade.message_builder import MessageBuilder
from pyblinktrade.message import JsonMessage

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

      print verification_data
      # [
      #   {
      #     "phone_number": "61111111",
      #     "name": {"middle": "", "last": "Larcerda", "first": "Carlos"},
      #     "created_at": 1411608625,
      #     "uploaded_files": [
      #       "https://www.jotformpro.com/uploads/pinhopro/42485268120958/287417823131147316/Scanned Image.jpg",
      #       "https://www.jotformpro.com/uploads/pinhopro/42485268120958/287417823131147316/Scanned-Image.jpg"
      #     ],
      #     "submissionID": "287417823131147316",
      #     "date_of_birth": "2014-JAN-1",
      #     "identification": {"australian_id": "11111111"},
      #     "address": {
      #         "city": "Santos",
      #         "street1": "Av. Floriano Peixoto, 277",
      #         "street2": "602",
      #         "state": "SP",
      #         "postal_code": "11209",
      #         "country_code": "Brazil"
      #     },
      #     "formID": "42485268120958"}
      # ]

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
  #wsdl_client = SoapClient( wsdl=wsdl, soap_ns="soapenv", ns="ns1",  trace=True)
  wsdl_client = SoapClient( wsdl=wsdl, soap_ns="soapenv", ns="ns1", add_children_ns=False, trace=True)

  verification_data = [
    {
       "phone_number": "61111111",
       "name": {
         "middle": "",
         "last": "Larcerda",
         "first": "Carlos"
       },
       "created_at": 1411608625,
       "uploaded_files": [
         "https://www.jotformpro.com/uploads/pinhopro/42485268120958/287417823131147316/Scanned Image.jpg",
         "https://www.jotformpro.com/uploads/pinhopro/42485268120958/287417823131147316/Scanned-Image.jpg"
       ],
       "submissionID": "287417823131147316",
       "date_of_birth": "2014-JAN-1",
       "identification": {"australian_id": "11111111"},
       "address": {
         "city": "Santos",
         "street1": "Av. Floriano Peixoto, 277",
         "street2": "602",
         "state": "SP",
         "postal_code": "11209",
         "country_code": "Brazil"
       },
       "formID": "42485268120958"
    }
  ]

  def get_verification_data(all_verification_data, key):
    value = None
    for data in reversed(all_verification_data):
      if key in data:
        value=data[key]
        break
    return value


  #a = wsdl_client.isUserIdRegistered( arguments.edentiti_customer_id, arguments.edentiti_password, 'g2rUPcc8'  )
  # <ns1:registerUser>
  #   <name>
  #     <givenName xmlns="http://services.registrations.edentiti.com/">JoAnn</givenName>
  #     <middleNames xmlns="http://services.registrations.edentiti.com/"></middleNames>
  #     <surname xmlns="http://services.registrations.edentiti.com/">Faryma</surname>
  #   </name>
  #   <email>email@gmail.com</email>
  #   <currentResidentialAddress>
  #     <country xmlns="http://services.registrations.edentiti.com/">US</country>
  #     <flatNumber xmlns="http://services.registrations.edentiti.com/">3G</flatNumber>
  #     <postcode xmlns="http://services.registrations.edentiti.com/">11209</postcode>
  #     <propertyName xmlns="http://services.registrations.edentiti.com/"></propertyName>
  #     <state xmlns="http://services.registrations.edentiti.com/">NY</state>
  #     <streetName xmlns="http://services.registrations.edentiti.com/">RIDGE BLVD</streetName>
  #     <streetNumber xmlns="http://services.registrations.edentiti.com/">7501</streetNumber>
  #     <streetType xmlns="http://services.registrations.edentiti.com/">st</streetType>
  #   <suburb xmlns="http://services.registrations.edentiti.com/"></suburb>
  #   </currentResidentialAddress><dob>2014-09-25T13:13:54.907593</dob>
  #   <homePhone>0262541234</homePhone>
  # </ns1:registerUser>


  a = wsdl_client.registerUser( customerId=arguments.edentiti_customer_id,
                            password=arguments.edentiti_password,
                            ruleId='default',
                            name={
                              'givenName': get_verification_data(verification_data, 'name')['first'],
                              'middleNames': get_verification_data(verification_data, 'name')['middle'],
                              'surname': get_verification_data(verification_data, 'name')['last']
                              },
                            currentResidentialAddress={
                              'country':get_verification_data(verification_data, 'address')['country_code'],
                              'flatNumber': get_verification_data(verification_data, 'address')['street2'],
                              'postcode': get_verification_data(verification_data, 'address')['postal_code'],
                              'propertyName':'',
                              'state':get_verification_data(verification_data, 'address')['state'],
                              'streetName':get_verification_data(verification_data, 'address')['street1'],
                              'streetNumber':'7501',
                              'streetType':'AVENUE',
                              'suburb':get_verification_data(verification_data, 'address')['city']
                            },
                            homePhone=get_verification_data(verification_data, 'phone_number'),
                            dob=datetime.datetime.today())

  print a




  return

  blinktrade_port = 443
  should_connect_on_ssl = True
  blinktrade_url = urlparse(arguments.blintrade_webscoket_url)
  if  blinktrade_url.port is None and blinktrade_url.scheme == 'ws':
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
