#-*- coding:utf-8 -*-
'''
20110406
todo: 1. 确认在Agent的prepare_base中使用sleep不会阻碍下一个数据的接收
      2. 完成当日的收盘作业
      3. 设计中间保存的格式
      4. 完成情景恢复

Agent的目的是合并行情和交易API到一个类中进行处理
    把行情和交易分开，从技术角度上来看挺好，但从使用者角度看就有些蛋疼了.
    正常都是根据行情决策

todo:
    1. 打通trade环节
    2. 前期数据的衔接(1分钟,5/30)
    3. 行情数据的整理
    4. trader桩的建立,根据trade桩模拟交易
    5. 中间环境的恢复,如持仓. 
       断点间的撤单--可延后. 要求撤单/委托动作都撤销后才能重起程序
    6. 完全模拟交易
    7. 有人值守实盘

    8. 生产环境必须考虑多个行情接入端, 有可能会出现延时情况.

后续工作
 B.1. 合约的自动匹配

关注ifuncs1a
xud_short_2
rsi_long_x2
xdown60
up0
ipmacd_long_t2
acd_da_sz_b2


##因为流控原因,所有Qry命令都用Command模式?
  不需要,可以忍受1s的延时. 因为行情通过别的来接收  

三类配置文件，都用INI格式记录
1. 基本配置 base.ini  这个是完全私人的
   记录登陆站点，登陆ID以及口令 

    [Base]
    ;User用于设定连接行情的设定 
    users = User1,User2,User3
    ;Trade用于设定连接交易端的设定
    traders = Trader1,Trader2

    [User1]
    port = 
    broker_id = 
    investor_id = 
    passwd = 

    [User2]
    ....

2. 策略配置 strategy.ini
   配置盯盘的合约
   配置交易的合约, 每个合约可以指定多个策略

   a. 保存行情的设置, 其中[Trace_Instruments]为合约类设置
[Trace_Instruments]
traces = IF,ru,fu,zn,rb,pb,m,a,c,y,b,l,p,v,SR,CF,TA,WS,RO,ER,WT
;a/al/au重复,c/cu重复
;traces = IF,ru,fu,cu,al,zn,au,rb,pb,m,a,c,y,b,l,p,v,SR,CF,TA,WS,RO,ER,WT
    ;[Trace_Instruments_Raw]为绝对设置
[Trace_Instruments_Raw]
IFs = IF1104,IF1105,IF1106,IF1109
CFs = CF109,CF107
   b. 交易策略定制 (todo:将来考虑自动判断主力合约) 
    [Alias_Def]
    IF_main = IF1105
    CF_main = CF109
    ;TODO:确定main之后,计算next,third,fourth,分别表示次合约、第三合约、第四合约. 找到主力合约后，按字母序确定
    [Trade_Config]
    ;如果策略文件为strategy，则可以不写
    ;strategy_file = strategy
    traces = IF_main,CF_main
    
    [IF_main]
    max_volume = 2
    strategys = IF_A,IF_B,IF_C

    [IF_A]
    max_holding = 2
    open_volume = 1
    opener = day_long_break
    closer = datr_long_stoper
    
    [IF_B]
    ...


3. 中断恢复状态 state.ini
   记录当前的持仓及相关策略,止损相关

    [Time_Stamp]
    lastupdate = 

    [Holdings]
    holdings = IF1104,IF1105,CF1109,

    [IF1104]
    instrment = IF1104
    long_volume = xxxx
    short_volume = xxxx
    h_long = IF1104_L1,IF1104_L2
    h_short = IF1104_S1,IF1104_S2

    [IF1104_L1]
    volume = xxxx
    opener = xxxx
    stoper = xxxx
    open_price = 3200
    current_stop_price = 3193

    [IF1104_L2]
    ...

    [IF1104_S1]
    ...

    [IF1105]
    ...
    ...

A. 中断恢复
   中断恢复是在创建instrment之后，重新初始化Position和Order的过程 
    


'''

import sched
import time
import logging
import thread
import threading
import bisect

from base import *
from dac import ATR,ATR1,STREND,STREND1,MA,MA1
import hreader

import UserApiStruct as ustruct
import UserApiType as utype
from MdApi import MdApi, MdSpi
from TraderApi import TraderApi, TraderSpi  

import config

#数据定义中唯一一个enum
THOST_TERT_RESTART  = 0
THOST_TERT_RESUME   = 1
THOST_TERT_QUICK    = 2

NFUNC = lambda data:None    #空函数桩

INSTS = [
         u'IF1104',u'IF1105',
         u'zn1104',u'zn1105'
        ]

INSTS_SAVE = [
         u'IF1104',u'IF1105',
         #郑州   
         u'CF109',u'CF111',
         u'ER109',u'ER111',
         u'RO109',u'RO111',
         u'TA105',u'TA106',
         u'WA109',u'WS111',
         #大连
         u'm1109',u'm1111',
         u'c1109',u'c1111',
         u'y1109',u'y1111',
         u'a1201',u'a1203',
         u'l1105',u'l1106',
         u'p1109',u'p1111',
         u'v1105',u'v1106',
         #上海
         u'rb1110',u'rb1111',
         u'zn1105',u'zn1106',
         u'al1105',u'al1106',
         u'cu1105',u'cu1106',
         u'ru1105',u'ru1106',
         u'fu1105',u'fu1106',
         ]  #必须采用ctp使用的合约名字，内部不做检验
#INSTS = [u'IF1103']  #必须采用ctp使用的合约名字，内部不做检验
#建议每跟踪的一个合约都使用一个行情-交易对. 因为行情的接收是阻塞式的,在做处理的时候会延误后面接收的行情
#套利时每一对合约都用一个行情-交易对
#INSTS = [u'IF1102']

#mylock = thread.allocate_lock()


class MdSpiDelegate(MdSpi):
    '''
        将行情信息转发到Agent
        并自行处理杂务
    '''
    logger = logging.getLogger('ctp.MdSpiDelegate')
    
    last_map = {}

    def __init__(self,
            instruments, #合约映射 name ==>c_instrument
            broker_id,   #期货公司ID
            investor_id, #投资者ID
            passwd, #口令
            agent,  #实际操作对象
        ):        
        self.instruments = set([name for name in instruments])
        self.broker_id =broker_id
        self.investor_id = investor_id
        self.passwd = passwd
        self.agent = agent
        ##必须在每日重新连接时初始化它. 这一点用到了生产行情服务器收盘后关闭的特点(模拟的不关闭)
        MdSpiDelegate.last_map = dict([(id,0) for id in instruments])

    def checkErrorRspInfo(self, info):
        if info.ErrorID !=0:
            logger.error(u"ErrorID:%s,ErrorMsg:%s" %(info.ErrorID,info.ErrorMsg))
        return info.ErrorID !=0

    def OnRspError(self, info, RequestId, IsLast):
        self.logger.error(u'requestID:%s,IsLast:%s,info:%s' % (RequestId,IsLast,str(info)))

    def OnFrontDisConnected(self, reason):
        self.logger.info(u'front disconnected,reason:%s' % (reason,))

    def OnFrontConnected(self):
        self.logger.info(u'front connected')
        self.user_login(self.broker_id, self.investor_id, self.passwd)

    def user_login(self, broker_id, investor_id, passwd):
        req = ustruct.ReqUserLogin(BrokerID=broker_id, UserID=investor_id, Password=passwd)
        r=self.api.ReqUserLogin(req,self.agent.inc_request_id())

    def OnRspUserLogin(self, userlogin, info, rid, is_last):
        self.logger.info(u'user login,info:%s,rid:%s,is_last:%s' % (info,rid,is_last))
        scur_day = int(time.strftime('%Y%m%d'))
        if scur_day > self.agent.scur_day:    #换日,重新设置volume
            print u'换日, %s-->%s' % (self.agent.scur_day,scur_day)
            self.agent.scur_day = scur_day
            MdSpiDelegate.last_map = dict([(id,0) for id in self.instruments])
        if is_last and not self.checkErrorRspInfo(info):
            self.logger.info(u"get today's trading day:%s" % repr(self.api.GetTradingDay()))
            self.subscribe_market_data(self.instruments)

    def subscribe_market_data(self, instruments):
        self.api.SubscribeMarketData(list(instruments))

    def OnRtnDepthMarketData(self, depth_market_data):
        #print depth_market_data.BidPrice1,depth_market_data.BidVolume1,depth_market_data.AskPrice1,depth_market_data.AskVolume1,depth_market_data.LastPrice,depth_market_data.Volume,depth_market_data.UpdateTime,depth_market_data.UpdateMillisec,depth_market_data.InstrumentID
        #print 'on data......\n',
        #with mylock:
        try:
            #mylock.acquire()
            #self.logger.debug(u'获得锁.................,mylock.id=%s' % id(mylock))        
            if depth_market_data.LastPrice > 999999 or depth_market_data.LastPrice < 10:
                self.logger.warning(u'收到的行情数据有误:%s,LastPrice=:%s' %(depth_market_data.InstrumentID,depth_market_data.LastPrice))
            if depth_market_data.InstrumentID not in self.instruments:
                self.logger.warning(u'收到未订阅的行情:%s' %(depth_market_data.InstrumentID,))
            #self.logger.debug(u'收到行情:%s,time=%s:%s' %(depth_market_data.InstrumentID,depth_market_data.UpdateTime,depth_market_data.UpdateMillisec))
            dp = depth_market_data
            self.logger.debug(u'收到行情，inst=%s,time=%s，volume=%s,last_volume=%s' % (dp.InstrumentID,dp.UpdateTime,dp.Volume,self.last_map[dp.InstrumentID]))
            if dp.Volume <= self.last_map[dp.InstrumentID]:
                self.logger.debug(u'行情无变化，inst=%s,time=%s，volume=%s,last_volume=%s' % (dp.InstrumentID,dp.UpdateTime,dp.Volume,self.last_map[dp.InstrumentID]))
                return  #行情未变化
            self.last_map[dp.InstrumentID] = dp.Volume
            #mylock.release()   #至此已经去掉重复的数据

            #self.logger.debug(u'after modify instrument=%s,lastvolume:%s,curVolume:%s' % (dp.InstrumentID,self.last_map[dp.InstrumentID],dp.Volume))
            #self.logger.debug(u'before loop')
            ctick = self.market_data2tick(depth_market_data)
            self.agent.RtnTick(ctick)
        finally:
            pass
            #mylock.release()   #至此主要工作完成
            #self.logger.debug(u'释放锁.................,mylock.id=%s' % id(mylock))
        

        #self.logger.debug(u'before write md:')
        ff = open(hreader.make_tick_filename(ctick.instrument),'a+')
        #print type(dp.UpdateMillisec),type(dp.OpenInterest),type(dp.Volume),type(dp.BidVolume1)
        #ff.write(u'%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' % (dp.TradingDay,dp.UpdateTime,dp.UpdateMillisec,dp.OpenInterest,dp.Volume,dp.LastPrice,dp.HighestPrice,dp.LowestPrice,dp.BidPrice1,dp.BidVolume1,dp.AskPrice1,dp.AskVolume1))
        try:
            ff.write(u'%(instrument)s,%(date)s,%(min1)s,%(sec)s,%(msec)s,%(holding)s,%(dvolume)s,%(price)s,%(high)s,%(low)s,%(bid_price)s,%(bid_volume)s,%(ask_price)s,%(ask_volume)s\n' % ctick.__dict__)
        except Exception,inst:
            print str(depth_market_data),str(depth_market_data.TradingDay),str(depth_market_data.UpdateTime)
        ff.close()
        #self.logger.debug(u'after write md:')
        #time.sleep(0.3)
        #self.logger.debug(u'after write sleep:')

    def market_data2tick(self,market_data):
        #market_data的格式转换和整理, 交易数据都转换为整数
        try:
            #rev的后四个字段在模拟行情中经常出错
            rev = BaseObject(instrument = market_data.InstrumentID,date=self.agent.scur_day,bid_price=0,bid_volume=0,ask_price=0,ask_volume=0)
            rev.min1 = int(market_data.UpdateTime[:2]+market_data.UpdateTime[3:5])
            rev.sec = int(market_data.UpdateTime[-2:])
            rev.msec = int(market_data.UpdateMillisec)
            rev.holding = int(market_data.OpenInterest+0.1)
            rev.dvolume = market_data.Volume
            rev.price = int(market_data.LastPrice*10+0.1)
            rev.high = int(market_data.HighestPrice*10+0.1)
            rev.low = int(market_data.LowestPrice*10+0.1)
            rev.bid_price = int(market_data.BidPrice1*10+0.1)
            rev.bid_volume = market_data.BidVolume1
            rev.ask_price = int(market_data.AskPrice1*10+0.1)
            rev.ask_volume = market_data.AskVolume1
            rev.date = int(market_data.TradingDay)
            rev.time = rev.date%10000 * 10000+ rev.min1*100 + rev.sec
        except Exception,inst:
            self.logger.warning(u'行情数据转换错误:%s' % str(inst))
        return rev

class TraderSpiDelegate(TraderSpi):
    '''
        将服务器回应转发到Agent
        并自行处理杂务
    '''
    logger = logging.getLogger('ctp.TraderSpiDelegate')    
    def __init__(self,
            instruments, #合约映射 name ==>c_instrument 
            broker_id,   #期货公司ID
            investor_id, #投资者ID
            passwd, #口令
            agent,  #实际操作对象
        ):        
        self.instruments = set([name for name in instruments])
        self.broker_id =broker_id
        self.investor_id = investor_id
        self.passwd = passwd
        self.agent = agent
        self.agent.set_spi(self)
 
    def isRspSuccess(self,RspInfo):
        return RspInfo == None or RspInfo.ErrorID == 0

    ##交易初始化
    def OnFrontConnected(self):
        '''
            当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用。
        '''
        self.logger.info(u'trader front connected')
        self.user_login(self.broker_id, self.investor_id, self.passwd)

    def OnFrontDisconnected(self, nReason):
        self.logger.info(u'trader front disconnected,reason=%s' % (nReason,))

    def user_login(self, broker_id, investor_id, passwd):
        req = ustruct.ReqUserLogin(BrokerID=broker_id, UserID=investor_id, Password=passwd)
        r=self.api.ReqUserLogin(req,self.agent.inc_request_id())

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        self.logger.info('trader login')
        self.logger.debug("loggin %s" % str(pRspInfo))
        if not self.isRspSuccess(pRspInfo):
            self.logger.warning(u'trader login failed, errMsg=%s' %(pRspInfo.ErrorMsg,))
            return
        self.agent.login_success(pRspUserLogin.FrontID,pRspUserLogin.SessionID,pRspUserLogin.MaxOrderRef)
        #self.settlementInfoConfirm()
        self.agent.set_trading_day(self.api.GetTradingDay())
        #self.query_settlement_info()
        self.query_settlement_confirm() 

    def OnRspUserLogout(self, pUserLogout, pRspInfo, nRequestID, bIsLast):
        '''登出请求响应'''
        self.logger.info(u'trader logout')

    def resp_common(self,rsp_info,bIsLast,name='默认'):
        #self.logger.debug("resp: %s" % str(rsp_info))
        if not self.isRspSuccess(rsp_info):
            self.logger.info(u"%s失败" % name)
            return -1
        elif bIsLast and self.isRspSuccess(rsp_info):
            self.logger.info(u"%s成功" % name)
            return 1
        else:
            self.logger.info(u"%s结果: 等待数据接收完全..." % name)
            return 0

    def query_settlement_confirm(self):
        '''
            这个基本没用，不如直接确认
            而且需要进一步明确：有史以来第一次确认前查询确认情况还是每天第一次确认查询情况时，返回的响应中
                pSettlementInfoConfirm为空指针. 如果是后者,则建议每日不查询确认情况,或者在generate_struct中对
                CThostFtdcSettlementInfoConfirmField的new_函数进行特殊处理
            CTP写代码的这帮家伙素质太差了，边界条件也不测试，后置断言也不整，空指针乱飞
            2011-3-1 确认每天未确认前查询确认情况时,返回的响应中pSettlementInfoConfirm为空指针
            并且妥善处理空指针之后,仍然有问题,在其中查询结算单无动静
        '''
        req = ustruct.QrySettlementInfoConfirm(BrokerID=self.broker_id,InvestorID=self.investor_id)
        self.api.ReqQrySettlementInfoConfirm(req,self.agent.inc_request_id())

    def query_settlement_info(self):
        #不填日期表示取上一天结算单,并在响应函数中确认
        self.logger.info(u'取上一日结算单信息并确认,BrokerID=%s,investorID=%s' % (self.broker_id,self.investor_id))
        req = ustruct.QrySettlementInfo(BrokerID=self.broker_id,InvestorID=self.investor_id,TradingDay=u'')
        #print req.BrokerID,req.InvestorID,req.TradingDay
        self.api.ReqQrySettlementInfo(req,self.agent.inc_request_id())

    def confirm_settlement_info(self):
        req = ustruct.SettlementInfoConfirm(BrokerID=self.broker_id,InvestorID=self.investor_id)
        self.api.ReqSettlementInfoConfirm(req,self.agent.inc_request_id())

    def OnRspQrySettlementInfo(self, pSettlementInfo, pRspInfo, nRequestID, bIsLast):
        '''请求查询投资者结算信息响应'''
        print u'Rsp 结算单查询'
        if(self.resp_common(pRspInfo,bIsLast,u'结算单查询')>0):
            print u'结算单内容:%s' % pSettlementInfo.Content
            self.logger.info(u'结算单内容:%s' % pSettlementInfo.Content)
            self.confirm_settlement_info()
        else:
            self.agent.initialize()
            

    def OnRspQrySettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        '''请求查询结算信息确认响应'''
        self.logger.debug(u"结算单确认信息查询响应:rspInfo=%s,结算单确认=%s" % (pRspInfo,pSettlementInfoConfirm))
        #self.query_settlement_info()
        if(self.resp_common(pRspInfo,bIsLast,u'结算单确认情况查询')>0):
            if(pSettlementInfoConfirm == None or int(pSettlementInfoConfirm.ConfirmDate) < self.agent.scur_day):
                #其实这个判断是不对的，如果周日对周五的结果进行了确认，那么周一实际上已经不需要再次确认了
                if(pSettlementInfoConfirm != None):
                    self.logger.info(u'最新结算单未确认，需查询后再确认,最后确认时间=%s,scur_day:%s' % (pSettlementInfoConfirm.ConfirmDate,self.agent.scur_day))
                else:
                    self.logger.info(u'结算单确认结果为None')
                self.query_settlement_info()
            else:
                self.logger.info(u'最新结算单已确认，不需再次确认,最后确认时间=%s,scur_day:%s' % (pSettlementInfoConfirm.ConfirmDate,self.agent.scur_day))
                self.agent.initialize()


    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        '''投资者结算结果确认响应'''
        if(self.resp_common(pRspInfo,bIsLast,u'结算单确认')>0):
            self.logger.info(u'结算单确认时间: %s-%s' %(pSettlementInfoConfirm.ConfirmDate,pSettlementInfoConfirm.ConfirmTime))
        self.agent.initialize()


    ###交易准备
    def OnRspQryInstrumentMarginRate(self, pInstrumentMarginRate, pRspInfo, nRequestID, bIsLast):
        '''
            保证金率回报。返回的必然是绝对值
        '''
        if bIsLast and self.isRspSuccess(pRspInfo):
            self.agent.rsp_qry_instrument_marginrate(pInstrumentMarginRate)
        else:
            #logging
            pass

    def OnRspQryInstrument(self, pInstrument, pRspInfo, nRequestID, bIsLast):
        '''
            合约回报。
        '''
        if bIsLast and self.isRspSuccess(pRspInfo):
            self.agent.rsp_qry_instrument(pInstrument)
            #print pInstrument
        else:
            #logging
            #print pInstrument
            self.agent.rsp_qry_instrument(pInstrument)  #模糊查询的结果,获得了多个合约的数据，只有最后一个的bLast是True


    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID, bIsLast):
        '''
            请求查询资金账户响应
        '''
        print u'查询资金账户响应'
        self.logger.debug(u'资金账户响应:%s' % pTradingAccount)
        if bIsLast and self.isRspSuccess(pRspInfo):
            self.agent.rsp_qry_trading_account(pTradingAccount)
        else:
            #logging
            pass

    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID, bIsLast):
        '''请求查询投资者持仓响应'''
        #print u'查询持仓响应',str(pInvestorPosition),str(pRspInfo)
        if self.isRspSuccess(pRspInfo): #每次一个单独的数据报
            self.agent.rsp_qry_position(pInvestorPosition)
        else:
            #logging
            pass

    def OnRspQryInvestorPositionDetail(self, pInvestorPositionDetail, pRspInfo, nRequestID, bIsLast):
        '''请求查询投资者持仓明细响应'''
        #print str(pInvestorPositionDetail)
        if self.isRspSuccess(pRspInfo): #每次一个单独的数据报
            self.agent.rsp_qry_position_detail(pInvestorPositionDetail)
        else:
            #logging
            pass


    def OnRspError(self, info, RequestId, IsLast):
        ''' 错误应答
        '''
        self.logger.error(u'requestID:%s,IsLast:%s,info:%s' % (RequestId,IsLast,str(info)))

    def OnRspQryOrder(self, pOrder, pRspInfo, nRequestID, bIsLast):
        '''请求查询报单响应'''
        if bIsLast and self.isRspSuccess(pRspInfo):
            self.agent.rsp_qry_order(pOrder)
        else:
            self.logger.error(u'requestID:%s,IsLast:%s,info:%s' % (nRequestID,bIsLast,str(pRspInfo)))
            pass

    def OnRspQryTrade(self, pTrade, pRspInfo, nRequestID, bIsLast):
        '''请求查询成交响应'''
        if bIsLast and self.isRspSuccess(pRspInfo):
            self.agent.rsp_qry_trade(pTrade)
        else:
            #logging
            pass


    ###交易操作
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID, bIsLast):
        '''
            报单未通过参数校验,被CTP拒绝
            正常情况后不应该出现
        '''
        print pRspInfo,nRequestID
        self.logger.warning(u'CTP报单录入错误回报, 正常后不应该出现,rspInfo=%s'%(str(pRspInfo),))
        #self.logger.warning(u'报单校验错误,ErrorID=%s,ErrorMsg=%s,pRspInfo=%s,bIsLast=%s' % (pRspInfo.ErrorID,pRspInfo.ErrorMsg,str(pRspInfo),bIsLast))
        #self.agent.rsp_order_insert(pInputOrder.OrderRef,pInputOrder.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)
        self.agent.err_order_insert(pInputOrder.OrderRef,pInputOrder.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)
    
    def OnErrRtnOrderInsert(self, pInputOrder, pRspInfo):
        '''
            交易所报单录入错误回报
            正常情况后不应该出现
            这个回报因为没有request_id,所以没办法对应
        '''
        print u'ERROR Order Insert'
        self.logger.warning(u'交易所报单录入错误回报, 正常后不应该出现,rspInfo=%s'%(str(pRspInfo),))
        self.agent.err_order_insert(pInputOrder.OrderRef,pInputOrder.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)
    
    def OnRtnOrder(self, pOrder):
        ''' 报单通知
            CTP、交易所接受报单
            Agent中不区分，所得信息只用于撤单
        '''
        #print repr(pOrder)
        self.logger.info(u'报单响应,Order=%s' % str(pOrder))
        if pOrder.OrderStatus == 'a':
            #CTP接受，但未发到交易所
            #print u'CTP接受Order，但未发到交易所, BrokerID=%s,BrokerOrderSeq = %s,TraderID=%s, OrderLocalID=%s' % (pOrder.BrokerID,pOrder.BrokerOrderSeq,pOrder.TraderID,pOrder.OrderLocalID)
            self.logger.info(u'CTP接受Order，但未发到交易所, BrokerID=%s,BrokerOrderSeq = %s,TraderID=%s, OrderLocalID=%s' % (pOrder.BrokerID,pOrder.BrokerOrderSeq,pOrder.TraderID,pOrder.OrderLocalID))
            self.agent.rtn_order(pOrder)
        else:
            #print u'交易所接受Order,exchangeID=%s,OrderSysID=%s,TraderID=%s, OrderLocalID=%s' % (pOrder.ExchangeID,pOrder.OrderSysID,pOrder.TraderID,pOrder.OrderLocalID)
            self.logger.info(u'交易所接受Order,exchangeID=%s,OrderSysID=%s,TraderID=%s, OrderLocalID=%s' % (pOrder.ExchangeID,pOrder.OrderSysID,pOrder.TraderID,pOrder.OrderLocalID))
            #self.agent.rtn_order_exchange(pOrder)
            self.agent.rtn_order(pOrder)

    def OnRtnTrade(self, pTrade):
        '''成交通知'''
        print u'成交通知,BrokerID=%s,BrokerOrderSeq = %s,exchangeID=%s,OrderSysID=%s,TraderID=%s, OrderLocalID=%s' %(pTrade.BrokerID,pTrade.BrokerOrderSeq,pTrade.ExchangeID,pTrade.OrderSysID,pTrade.TraderID,pTrade.OrderLocalID)
        self.logger.info(u'成交回报,Trade=%s' % repr(pTrade))
        self.agent.rtn_trade(pTrade)

    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID, bIsLast):
        '''
            ctp撤单校验错误
        '''
        self.logger.warning(u'CTP撤单录入错误回报, 正常后不应该出现,rspInfo=%s'%(str(pRspInfo),))
        #self.agent.rsp_order_action(pInputOrderAction.OrderRef,pInputOrderAction.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)
        self.agent.err_order_action(pInputOrderAction.OrderRef,pInputOrderAction.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)

    def OnErrRtnOrderAction(self, pOrderAction, pRspInfo):
        ''' 
            交易所撤单操作错误回报
            正常情况后不应该出现
        '''
        self.logger.warning(u'交易所撤单录入错误回报, 可能已经成交,rspInfo=%s'%(str(pRspInfo),))
        self.agent.err_order_action(pOrderAction.OrderRef,pOrderAction.InstrumentID,pRspInfo.ErrorID,pRspInfo.ErrorMsg)


class c_instrument(object):
    @staticmethod
    def create_instruments(names,strategy):
        '''根据名称序列和策略序列创建instrument
           其中策略序列的结构为:
           [总最大持仓量,策略1,策略2...] 
        '''
        objs = dict([(name,c_instrument(name)) for name in names])
        for name,item in strategy:
            if name not in objs:
                print u'策略针对合约%s不在盯盘列表中' % (name,)
                continue
            objs[name].max_volume = item[0] #
            objs[name].strategy = dict([(ss.get_name(),ss) for ss in item[1:]])
            objs[name].initialize_positions()
        return objs

    def __init__(self,name):
        self.name = name
        #保证金率
        self.marginrate = (0,0) #(多,空)
        #合约乘数
        self.multiple = 0
        #最小跳动
        self.tick_base = 0  #单位为0.1
        #持仓量
        #BaseObject(hlong,hshort,clong,cshort) #历史多、历史空、今日多、今日空 #必须与实际数据一致, 实际上没用到
        self.position = BaseObject(hlong=0,hshort=0,clong=0,cshort=0)
        #持仓明细策略名==>Position #(合约、策略名、策略、基准价、基准时间、orderref、持仓方向、持仓量、当前止损价)
        self.position_detail = {}   #在Agent的ontrade中设定, 并需要在resume中恢复
        #设定的最大持仓手数
        self.max_volume = 1

        #应用策略 开仓函数名 ==> BaseObject(instrument_id,strategy_name,position_type,volume,stoper)
        self.strategy = {}
        
        #行情数据
        #其中tdata.m1/m3/m5/m15/m30/d1为不同周期的数据
        #   tdata.cur_min是当前分钟的行情，包括开盘,最高,最低,当前价格,持仓,累计成交量
        #   tdata.cur_day是当日的行情，包括开盘,最高,最低,当前价格,持仓,累计成交量, 其中最高/最低有两类，一者是tick的当前价集合得到的，一者是tick中的最高/最低价得到的
        self.t2order = t2order_if if hreader.is_if(self.name) else t2order_com
        self.data = BaseObject()
        self.begin_flag = False #save标志，默认第一个不保存, 因为第一次切换的上一个是历史数据

    def initialize_positions(self): #根据策略初始化头寸为0
        self.position_detail = dict([(ss.get_name(),Position(self.name,ss)) for ss in self.strategy.values()])

    def calc_remained_volume(self):   #计算剩余的可开仓量
        locked_volume = 0
        for position in self.position_detail.values():
            locked_volume += position.get_locked_volume()
        return self.max_volume - locked_volume if self.max_volume > locked_volume else 0

    def calc_margin_amount(self,price,direction):   
        '''
            计算保证金
            所有price以0.1为基准
            返回的保证金以1为单位
        '''
        my_marginrate = self.marginrate[0] if direction == LONG else self.marginrate[1]
        if self.name[:2].upper == 'IF':
            return price / 10.0 * self.multiple * my_marginrate 
        else:
            return price * self.multiple * my_marginrate 

    def make_target_price(self,price,direction): 
        '''
            计算开平仓时的溢出价位
            传入的price以0.1为单位
            返回的目标价以1为单位
        '''
        return (price + SLIPPAGE_BASE * self.tick_base if direction == LONG else price-SLIPPAGE_BASE * self.tick_base)/10.0

    def get_order(self,vtime):
        return self.t2order[vtime]

class AbsAgent(object):
    ''' 抽取与交易无关的功能，便于单独测试
    '''
    def __init__(self):
        ##命令队列(不区分查询和交易)
        self.commands = []  #每个元素为(trigger_tick,func), 用于当tick==trigger_tick时触发func
        self.tick = 0

    def inc_tick(self):
        self.tick += 1
        self.check_commands()
        return self.tick

    def get_tick(self):
        return self.tick

    def put_command(self,trigger_tick,command): #按顺序插入
        cticks = [ttick for ttick,command in self.commands]
        ii = bisect.bisect(cticks,trigger_tick)
        self.commands.insert(ii,(trigger_tick,command))

    def check_commands(self):   
        '''
            执行命令队列中触发时间<=当前tick的命令. 注意一个tick=0.5s
            以后考虑一个tick只触发一个命令?
        '''
        l = len(self.commands)
        i = 0
        while(i<l and self.tick >= self.commands[i][0]):
            self.commands[i][1]()
            i += 1
        del self.commands[0:i]


class Agent(AbsAgent):
    logger = logging.getLogger('ctp.agent')

    def __init__(self,trader,cuser,instruments,my_strategy,tday=0):
        '''
            trader为交易对象
            tday为当前日,为0则为当日
        '''
        AbsAgent.__init__(self)
        ##计时, 用来激发队列
        ##
        self.trader = trader
        self.cuser = cuser
        self.strategy = my_strategy
        self.instruments = c_instrument.create_instruments(instruments,my_strategy)
        self.request_id = 1
        self.initialized = False
        self.data_funcs = []  #计算函数集合. 如计算各类指标, 顺序关系非常重要
                              #每一类函数由一对函数组成，.sfunc计算序列用，.func1为动态计算用，只计算当前值
                              #接口为(data), 从data的属性中取数据,并计算另外一些属性
        ###交易
        self.lastupdate = 0
        self.transmitting_orders = {}    #orderref==>order,发出后等待回报的指令, 回报后到holding
        #self.queued_orders = []     #因为保证金原因等待发出的指令(合约、策略族、基准价、基准时间(到秒))
        self.front_id = None
        self.session_id = None
        self.order_ref = 1
        self.trading_day = 20110101
        self.scur_day = int(time.strftime('%Y%m%d')) if tday==0 else tday
        #当前资金/持仓
        self.available = 0  #可用资金
        ##查询命令队列
        self.qry_commands = []  #每个元素为查询命令，用于初始化时查询相关数据
        
        #计算函数 sfunc为序列计算函数(用于初始计算), func1为动态计算函数(用于分钟完成时的即时运算)
        self.register_data_funcs(
                BaseObject(sfunc=NFUNC,func1=hreader.time_period_switch),    #时间切换函数
                BaseObject(sfunc=ATR,func1=ATR1),
                BaseObject(sfunc=MA,func1=MA1),
                BaseObject(sfunc=STREND,func1=STREND1),
            )

        #初始化
        hreader.prepare_directory(instruments)
        self.prepare_data_env()
        #调度器
        self.scheduler = sched.scheduler(time.time, time.sleep)
        #保存锁
        self.lock = threading.Lock()
        #保存分钟数据标志
        self.save_flag = False  #默认不保存

        self.init_init()    #init中的init,用于子类的处理

    def init_init(self):
        pass

    def set_spi(self,spi):
        self.spi = spi

    def inc_request_id(self):
        self.request_id += 1
        return self.request_id

    def inc_order_ref(self):
        self.order_ref += 1
        return self.order_ref

    def set_trading_day(self,trading_day):
        self.trading_day = trading_day

    def get_trading_day(self):
        return self.trading_day

    def login_success(self,frontID,sessionID,max_order_ref):
        self.front_id = frontID
        self.session_id = sessionID
        self.order_ref = int(max_order_ref)

    def initialize(self):
        '''
            初始化，如保证金率，账户资金等
        '''
        ##必须先把持仓初始化成配置值或者0
        self.qry_commands.append(self.fetch_trading_account)
        for inst in self.instruments:
            self.qry_commands.append(fcustom(self.fetch_instrument,instrument_id = inst))
            self.qry_commands.append(fcustom(self.fetch_instrument_marginrate,instrument_id = inst))
            self.qry_commands.append(fcustom(self.fetch_investor_position,instrument_id = inst))
        time.sleep(1)   #保险起见
        self.check_qry_commands()
        self.initialized = True #避免因为断开后自动重连造成的重复访问

    def check_qry_commands(self):
        #必然是在rsp中要发出另一个查询
        if len(self.qry_commands)>0:
            time.sleep(1)   #这个只用于非行情期的执行. 
            self.qry_commands[0]()
            del self.qry_commands[0]
        print u'查询命令序列长度:',len(self.qry_commands)


    def prepare_data_env(self):
        '''
            准备数据环境, 如需要的30分钟数据
        '''
        hdatas = hreader.prepare_data([name for name in self.instruments],self.scur_day)
        for hdata in hdatas.values():
            self.instruments[hdata.name].data = hdata
            for dfo in self.data_funcs:
                dfo.sfunc(hdata)
            
    def register_data_funcs(self,*funcss):
        for funcs in funcss:
            self.data_funcs.append(funcs)

    ##内务处理
    def fetch_trading_account(self):
        #获取资金帐户
        print u'获取资金帐户..'
        req = ustruct.QryTradingAccount(BrokerID=self.cuser.broker_id, InvestorID=self.cuser.investor_id)
        r=self.trader.ReqQryTradingAccount(req,self.inc_request_id())
        print u'查询资金账户, 函数发出返回值:%s' % r

    def fetch_investor_position(self,instrument_id):
        #获取合约的当前持仓
        print u'获取合约%s的当前持仓..' % (instrument_id,)
        req = ustruct.QryInvestorPosition(BrokerID=self.cuser.broker_id, InvestorID=self.cuser.investor_id,InstrumentID=instrument_id)
        r=self.trader.ReqQryInvestorPosition(req,self.inc_request_id())
        print u'查询持仓, 函数发出返回值:%s' % r
    
    def fetch_investor_position_detail(self,instrument_id):
        '''
            获取合约的当前持仓明细，目前没用
        '''
        print u'获取合约%s的当前持仓..' % (instrument_id,)
        req = ustruct.QryInvestorPositionDetail(BrokerID=self.cuser.broker_id, InvestorID=self.cuser.investor_id,InstrumentID=instrument_id)
        r=self.trader.ReqQryInvestorPositionDetail(req,self.inc_request_id())
        print u'查询持仓, 函数发出返回值:%s' % r

    def fetch_instrument_marginrate(self,instrument_id):
        req = ustruct.QryInstrumentMarginRate(BrokerID=self.cuser.broker_id,
                        InvestorID=self.cuser.investor_id,
                        InstrumentID=instrument_id,
                        HedgeFlag = utype.THOST_FTDC_HF_Speculation
                )
        r = self.trader.ReqQryInstrumentMarginRate(req,self.inc_request_id())
        print u'查询保证金率, 函数发出返回值:%s' % r

    def fetch_instrument(self,instrument_id):
        req = ustruct.QryInstrument(
                        InstrumentID=instrument_id,
                )
        r = self.trader.ReqQryInstrument(req,self.inc_request_id())
        print u'查询合约, 函数发出返回值:%s' % r

    def fetch_instruments_by_exchange(self,exchange_id):
        '''不能单独用exchange_id,因此没有意义
        '''
        req = ustruct.QryInstrument(
                        ExchangeID=exchange_id,
                )
        r = self.trader.ReqQryInstrument(req,self.inc_request_id())
        print u'查询合约, 函数发出返回值:%s' % r

    ##交易处理
    def RtnTick(self,ctick):#行情处理主循环
        #print u'in my lock, close长度:%s,ma_5长度:%s\n' %(len(self.instrument[ctick.instrument].data.sclose),len(self.instrument[ctick.instrument].data.ma_5))
        inst = ctick.instrument
        self.prepare_tick(ctick)
        #先平仓
        close_positions = self.check_close_signal(ctick)
        if len(close_positions)>0:
            self.make_command(close_positions)
        #再开仓.
        open_signals = self.check_open_signal(ctick)
        if len(open_signals) > 0:
            self.make_command(open_signals)
        #检查待发出命令
        self.check_commands()
        ##扫尾
        self.finalize()
        #print u'after my lock, close长度:%s,ma_5长度:%s\n' %(len(self.instrument[ctick.instrument].data.sclose),len(self.instrument[ctick.instrument].data.ma_5))
        
    def prepare_tick(self,ctick):
        '''
            准备计算, 包括分钟数据、指标的计算
        '''
        inst = ctick.instrument
        if inst not in self.instruments:
            logger.info(u'接收到未订阅的合约数据:%s' % (inst,))
        dinst = self.instruments[inst]#.data
        if(self.prepare_base(dinst,ctick)):  #如果切分分钟则返回>0
            for func in self.data_funcs:    #动态计算
                func.func1(dinst.data)

    def day_finalize(self,dinst,last_min,last_sec):
        '''指定ddata的日结操作
           将当日数据复制到history.txt 
        '''
        #print ddata.name,last_min,last_sec
        with self.lock:
            ddata = dinst.data
            '''
            if ddata.cur_min.vtime > last_min:  #存在151500或150000,不需要继续转换
                print u'%s存在151500或150000,ddata.cur_min=%s,last_min=%s' % (ddata.name,ddata.cur_min.vtime,last_min)
                self.logger.info(u'%s存在151500或150000,ddata.cur_min=%s,last_min=%s' % (ddata.name,ddata.cur_min,last_min))
            else:   #不存在151500或150000.则将最后一分钟保存
                self.save_min(dinst)
            '''
            last_current_time = hreader.read_current_last(dinst.name).time
            print 'time:',last_current_time,last_min
            if last_current_time < last_min:    #如果已经有当分钟的记录，就不再需要保存了。
                self.save_min(dinst)  
            #print 'in day_finalize'
            hreader.check_merge(ddata.name,self.scur_day)

    def save_min(self,dinst):
        ddata = dinst.data
        ddata.sdate.append(ddata.cur_min.vdate)
        ddata.stime.append(ddata.cur_min.vtime)
        ddata.sopen.append(ddata.cur_min.vopen)
        ddata.sclose.append(ddata.cur_min.vclose)
        ddata.shigh.append(ddata.cur_min.vhigh)
        ddata.slow.append(ddata.cur_min.vlow)
        ddata.sholding.append(ddata.cur_min.vholding)
        ddata.svolume.append(ddata.cur_min.vvolume)
        ddata.siorder.append(dinst.get_order(ddata.cur_min.vtime))
        #print 'in save_min'
        ##需要save下
        if self.save_flag == True:
            hreader.save1(dinst.name,ddata.cur_min,self.scur_day)

    def prepare_base(self,dinst,ctick):
        '''
            返回值标示是否是分钟的切换
            这里没有处理15:00:00的问题
        '''
        rev = False #默认不切换
        ctick.iorder = dinst.get_order(ctick.min1)
        ddata = dinst.data
        if (ctick.iorder == ddata.cur_min.viorder + 1 and (ctick.sec > 0 or ctick.msec>0)) or ctick.iorder > ddata.cur_min.viorder + 1 or ctick.date > ddata.cur_min.vdate:#时间切换. 00秒00毫秒属于上一分钟, 但如果下一单是隔了n分钟的，也直接切换
            rev = True
            #print ctick.min1,ddata.cur_min.vtime,ctick.date,ddata.cur_min.vdate
            if (len(ddata.stime)>0 and (ctick.date > ddata.sdate[-1] or ctick.min1 > ddata.stime[-1])) or len(ddata.stime)==0:#已有分钟与已保存的有差别
                ''' #2011-05-01 去掉. 因为把00归入上一分钟
                #这里把00秒归入到新的分钟里面. todo:需要把00归入到老的分钟??一切都迎刃而解
                if (hreader.is_if(ctick.instrument) and ctick.min1 == 1515 and ctick.sec==0) or (not hreader.is_if(ctick.instrument) and ctick.min1 == 1500 and ctick.sec==0): #最后一秒钟算1514/1500的, 需要处理没有1500/1515时候的最后一分钟
                    print u'最后一秒钟....'
                    ddata.cur_min.vclose = ctick.price
                    if ctick.price > ddata.cur_min.vhigh:
                        ddata.cur_min.vhigh = ctick.price
                    if ctick.price < ddata.cur_min.vlow:
                        ddata.cur_min.vlow = ctick.price
                    ddata.cur_min.vholding = ctick.holding
                    ddata.cur_min.vvolume += (ctick.dvolume - ddata.cur_day.vvolume)
                '''
                #if ddata.cur_min.vdate != 0:    #不是史上第一个
                #    #print u'正常保存分钟数据.......'
                #    self.save_min(dinst)
                #else:#是史上第一分钟，之前的cur_min是默认值, 即无保存价值
                #    #print u'不保存分钟数据,date=%s' % (ddata.cur_min.vdate)
                #    rev = False
                if dinst.begin_flag:
                    #print u'保存分钟数据,date=%s,time=%s' % (ddata.cur_min.vdate,ddata.cur_min.vtime)
                    self.save_min(dinst)
                else:
                    #print u'第-1分钟数据不保存,date=%s,time=%s' % (ddata.cur_min.vdate,ddata.cur_min.vtime)
                    dinst.begin_flag = True
                    rev = False
            ddata.cur_min.vdate = ctick.date
            ddata.cur_min.vtime = ctick.min1
            ddata.cur_min.vopen = ctick.price
            ddata.cur_min.vclose = ctick.price
            ddata.cur_min.vhigh = ctick.price
            ddata.cur_min.vlow = ctick.price
            ddata.cur_min.vholding = ctick.holding
            ddata.cur_min.vvolume = ctick.dvolume - ddata.cur_day.vvolume if ctick.date == ddata.cur_day.vdate else ctick.dvolume
            ddata.cur_min.viorder = ctick.iorder
            #print 'in change:',ddata.cur_min.vvolume
        elif ctick.iorder == ddata.cur_min.viorder or (ctick.iorder == ddata.cur_min.viorder + 1 and ctick.sec == 0 and ctick.msec==0):#当分钟的处理. 在接续时，如果resume时间正好是当分钟，会发生当分钟重复计数
            #print ddata.cur_min.vvolume,ctick.dvolume,ddata.cur_day.vvolume,ctick.time,ctick.sec,ctick.msec
            ddata.cur_min.vclose = ctick.price
            if ctick.price > ddata.cur_min.vhigh:
                ddata.cur_min.vhigh = ctick.price
            if ctick.price < ddata.cur_min.vlow:
                ddata.cur_min.vlow = ctick.price
            ddata.cur_min.vholding = ctick.holding
            ddata.cur_min.vvolume += (ctick.dvolume - ddata.cur_day.vvolume)
            #print ddata.cur_min.vvolume
        else:#早先的tick，只在测试时用到
            pass
        ##日的处理
        if ctick.date != ddata.cur_day.vdate:
            ddata.cur_day.vdate = ctick.date
            ddata.cur_day.vopen = ctick.price
            ddata.cur_day.vhigh = ctick.price
            ddata.cur_day.vlow = ctick.price
        else:
            if ctick.price > ddata.cur_day.vhigh:
                ddata.cur_day.vhigh = ctick.price   #根据当前价比较得到的最大/最小
            if ctick.price < ddata.cur_day.vlow:
                ddata.cur_day.vlow = ctick.price
        ddata.cur_day.vholding = ctick.holding
        ddata.cur_day.vvolume = ctick.dvolume
        ddata.cur_day.vhighd = ctick.high   #服务器传过来的最大/最小
        ddata.cur_day.vlowd = ctick.low
        ddata.cur_day.vclose = ctick.price
        #if (hreader.is_if(ctick.instrument) and ctick.min1 == 1514 and ctick.sec==59) or (not hreader.is_if(ctick.instrument) and ctick.min1 == 1459 and ctick.sec==59): #收盘作业
        if ddata.cur_min.viorder == 270 and ctick.sec == 59 and ctick.min1 >=ddata.cur_min.vtime: #避免收到历史行情引发问题
            #print 'in closing',ddata.cur_min.viorder,ctick.sec,ddata.cur_min.vtime,ctick.min1
            threading.Timer(1,self.day_finalize,args=[dinst,ctick.min1,ctick.sec]).start()
            #self.day_finalize(dinst,ctick.min1,ctick.sec)
        #threading.Timer(3,self.day_finalize,args=[dinst,ctick.min1,ctick.sec]).start()
        return rev
    
    def check_close_signal(self,ctick):
        '''
            检查平仓信号
            #TODO: 必须考虑出现平仓信号时，position还没完全成交的情况
                   在OnTrade中进行position的细致处理 
        '''
        signals = []
        if ctick.instrument not in self.instruments:
            self.logger.warning(u'需要监控的%s未记录行情数据')
            print u'需要监控的%s未记录行情数据'
            return signals
        cur_inst = self.instruments[ctick.instrument]
        is_touched = False  #止损位变化
        for position in cur_inst.position_detail.values():
            for order in position.orders:
                if order.opened_volume > 0:
                    mysignal = order.stoper.check(cur_inst.data,ctick)
                    if mysignal[0] != 0:    #止损
                        signals.append(BaseObject(instrument=cur_inst,
                                volume=order.opened_volume,
                                direction = order.stoper.direction,
                                base_price = mysignal[1],
                                price=order.stoper.calc_target_price(mysignal[1],cur_inst.tick_base),
                                source_order = order, #原始头寸
                                mytime = ctick.time,
                                action_type = XCLOSE,
                            )
                        )
                    if mysignal[2] != 0:#止损位置变化
                        is_touched = True
        if is_touched:
            self.save_state()
        return signals

    def check_open_signal(self,ctick):
        '''
            检查开仓信号返回信号集合[s1,s2,....]
            其中每个元素包含以下属性:
                合约号
                开仓方向
                开仓策略
                平仓函数
                最大手数
                基准价
        '''
        signals = []
        if ctick.instrument not in self.instruments:
            self.logger.warning(u'需要监控的%s未记录行情数据')
            print u'需要监控的%s未记录行情数据'
            return signals
        cur_inst = self.instruments[ctick.instrument]
        for ss in cur_inst.strategy.values():
            mysignal = ss.opener.check(cur_inst.data,ctick)
            if mysignal[0] != 0:
                base_price = mysignal[1] if mysignal[1]>0 else ctick.price
                candidate = Order(instrument=cur_inst,
                                position=cur_inst.position_detail[ss.name],
                                base_price=base_price,
                                target_price=strategy.opener.calc_target_price(base_price,cur_inst.tick_base),
                                mytime = ctike.time,
                                action_type=XOPEN,
                            )
                candidate.volume = self.calc_open_volume(instrument,order)
                if candidate.volume > 0:
                    self.available -= (want_volume *margin_amount)  #锁定保证金
                    signals.append(candidate)
        return signals

    def calc_open_volume(self,instrument,order):
        '''
            计算order的可开仓数
            instrument: 合约对象
        '''
        want_volume = order.position.calc_open_volume()
        if want_volume <= 0:
            return 0
        margin_amount = instrument.calc_margin_amount(order.target_price,order.strategy.direction)
        if margin_amount <= 1:#不可能只有1块钱
            self.logger.error(u'合约%s保证金率未初始化' % (instrument.name,))
            print u'合约%s保证金率未初始化' % (instrument.name,)
        available_volume = int(self.available / margin_amount)
        if available_volume == 0:
            return 0
        if want_volume > availabel_volume:
            want_volume = availabel_volume
        return want_volume

    def make_command(self,orders):
        '''
            根据下单指令进行开/平仓
            开仓时,埋入一分钟后的撤单指令
            TODO: 平仓时考虑直接用市价单
        '''
        for order in orders:
            order.order_ref = self.inc_order_ref()
            command = BaseObject(instrument = order.instrument.name,
                    direction = order.direction,
                    price = order.target_price/10.0, #内部都是以0.1为计量单位
                    volume = order.volume,
                    order_ref = order.order_ref,
                    action_type = order.action_type,
                )
            if order.action_type == XOPEN:##开仓情况,X跳后不论是否成功均撤单
                self.transmitting_orders[command.order_ref] = order
                ##初始化止损类
                order.stoper = order.position.strategy.stoper(order.instrument.data,order.base_price)
                self.put_command(self.get_tick()+order.position.strategy.opener.valid_length,fcustom(self.cancel_command,command=command))
                self.open_position(command)
            else:#平仓, Y跳后不论是否成功均撤单, 撤单应该比开仓更快，避免追不上
                self.transmitting_orders[command.order_ref] = order.source_order
                self.put_command(self.get_tick()+position.stoper.valid_length,fcustom(self.cancel_command,command=command))
                self.close_position(command)

    def open_position(self,order):
        ''' 
            发出下单指令
        '''
        req = ustruct.InputOrder(
                InstrumentID = order.instrument,
                Direction = order.direction,
                OrderRef = str(order.order_ref),
                LimitPrice = order.price,   #有个疑问，double类型如何保证舍入舍出，在服务器端取整?
                VolumeTotalOriginal = order.volume,
                OrderPriceType = utype.THOST_FTDC_OPT_LimitPrice,
                
                BrokerID = self.cuser.broker_id,
                InvestorID = self.cuser.investor_id,
                CombOffsetFlag = utype.THOST_FTDC_OF_Open,         #开仓 5位字符,但是只用到第0位
                CombHedgeFlag = utype.THOST_FTDC_HF_Speculation,   #投机 5位字符,但是只用到第0位

                VolumeCondition = utype.THOST_FTDC_VC_AV,
                MinVolume = 1,  #这个作用有点不确定,有的文档设成0了
                ForceCloseReason = utype.THOST_FTDC_FCC_NotForceClose,
                IsAutoSuspend = 1,
                UserForceClose = 0,
                TimeCondition = utype.THOST_FTDC_TC_GFD,
            )
        r = self.trader.ReqOrderInsert(req,self.inc_request_id())


    def close_position(self,order,CombOffsetFlag = utype.THOST_FTDC_OF_CloseToday):
        ''' 
            发出平仓指令. 默认平今仓
        '''
        req = ustruct.InputOrder(
                InstrumentID = order.instrument,
                Direction = order.direction,
                OrderRef = str(order.order_ref),
                LimitPrice = order.price,
                VolumeTotalOriginal = order.volume,
                CombOffsetFlag = CombOffsetFlag,
                OrderPriceType = utype.THOST_FTDC_OPT_LimitPrice,
                
                BrokerID = self.cuser.broker_id,
                InvestorID = self.cuser.investor_id,
                CombHedgeFlag = utype.THOST_FTDC_HF_Speculation,   #投机 5位字符,但是只用到第0位

                VolumeCondition = utype.THOST_FTDC_VC_AV,
                MinVolume = 1,  #TODO:这个有点不确定. 需要测试确认
                ForceCloseReason = utype.THOST_FTDC_FCC_NotForceClose,
                IsAutoSuspend = 1,
                UserForceClose = 0,
                TimeCondition = utype.THOST_FTDC_TC_GFD,
            )
        r = self.trader.ReqOrderInsert(req,self.inc_request_id())

    def cancel_command(self,command):
        '''
            发出撤单指令
        '''
        req = ustruct.InputOrderAction(
                InstrumentID = command.instrument,
                OrderRef = str(command.order_ref),
                
                BrokerID = self.cuser.broker_id,
                InvestorID = self.cuser.investor_id,
                FrontID = self.front_id,
                SessionID = self.session_id,
                ActionFlag = utype.THOST_FTDC_AF_Delete,
                #OrderActionRef = self.inc_order_ref()  #没用,不关心这个，每次撤单成功都需要去查资金
            )
        r = self.trader.ReqOrderAction(req,self.inc_request_id())


    def finalize(self):
        pass

    def save_state(self):
        '''
            保存环境
        '''
        state = BaseObject(last_update=int(time.strftime('%Y%m%d')),holdings={})
        cur_orders = {} #instrument==>orders
        for inst in self.instruments.values():
            for position in inst.position_detail.values():
                if position.opened_volume>0:
                    iorders = cur_orders.setdefault(position.instrument,[])
                    iorders.extend([order for order in position.orders if order.opened_volume>0])
        for inst,orders in cur_orders.items():
            cin = BaseObject(instrument = inst,opened_volume=sum([order.opened_volume for order in orders]),orders=orders)
            state.holdings[inst] = cin
        config.save_state(state)
        return
            
    def resume(self):
        '''
            恢复环境
            对每一个合约:
                1. 获得必要的历史数据
                2. 获得当日分钟数据, 并计算相关指标
                3. 获得当日持仓，并初始化止损. 
                暂时要求历史数据和当日已发生的分钟数据保存在一个文件里面整体读取
        '''
        state = config.parse_state(self.strategy)
        cposs = set([])
        for chd in state.holdings:
            cur_inst = self.instruments[chd.instrument]
            for order in chd.orders:
                cur_position = cur_inst.position_detail[order.strategy_name]
                cur_position.add_order(order)
                cposs.add(cur_position)
        for pos in cposs:
            pos.re_calc()


    ###交易

    ###回应
    def rtn_trade(self,strade):
        '''
            成交回报
            #TODO: 必须考虑出现平仓信号时，position还没完全成交的情况
                   在OnTrade中进行position的细致处理 
            #TODO: 必须处理策略分类持仓汇总和持仓总数不匹配时的问题
        '''
        if strade.OrderRef not in self.transmitting_orders or strade.InstrumentID not in self.instruments:
            self.logger.warning(u'收到非本程序发出的成交回报:%s-%s' % (strade.InstrumentID,strade.OrderRef))
        cur_inst = self.instruments[strade.InstrumentID]
        myorder = self.transmitting_orders[int(strade.OrderRef)]
        if myorder.action_type == XOPEN:#开仓, 也可用pTrade.OffsetFlag判断
            myorder.on_trade(price=int(strade.Price*10+0.1),volume=strade.Volume,trade_time=strade.TradeTime)
        else:
            myorder.source_order.on_close(price=int(strade.Price*10+0.1),volume=strade.Volume,trade_time=strade.TradeTime)
        self.save_state()
        ##查询可用资金
        self.put_command(self.get_tick()+1,self.fetch_trading_account)


    def rtn_order(self,sorder):
        '''
            交易所接受下单回报(CTP接受的已经被过滤)
            暂时只处理撤单的回报. 
        '''
        #print str(sorder)
        if sorder.OrderStatus == utype.THOST_FTDC_OST_Canceled or sorder.OrderStatus == utype.THOST_FTDC_OST_PartTradedNotQueueing:   #完整撤单或部成部撤
            ##查询可用资金
            self.put_command(self.get_tick()+1,self.fetch_trading_account)

    def err_order_insert(self,order_ref,instrument_id,error_id,error_msg):
        '''
            ctp/交易所下单错误回报，不区分ctp和交易所
            正常情况下不应当出现
        '''
        pass    #可以忽略

    def err_order_action(self,order_ref,instrument_id,error_id,error_msg):
        '''
            ctp/交易所撤单错误回报，不区分ctp和交易所
            不处理，可记录
        '''
        pass    #可能撤单已经成交
    
    ###辅助   
    def rsp_qry_position(self,position):
        '''
            查询持仓回报, 每个合约最多得到4个持仓回报，历史多/空、今日多/空
        '''
        #print u'agent 持仓:',str(position)
        if position != None:    
            cur_position = self.instruments[position.InstrumentID].position
            if position.PosiDirection == utype.THOST_FTDC_PD_Long:
                if position.PositionDate == utype.THOST_FTDC_PSD_Today:
                    cur_position.clong = position.Position  #TodayPosition
                else:
                    cur_position.hlong = position.Position  #YdPosition
            else:#空头
                if position.PositionDate == utype.THOST_FTDC_PSD_Today:
                    cur_position.cshort = position.Position #TodayPosition
                else:
                    cur_position.hshort = position.Position #YdPosition
        else:#无持仓信息，保持默认设置
            pass
        self.check_qry_commands() 

    def rsp_qry_instrument_marginrate(self,marginRate):
        '''
            查询保证金率回报. 
        '''
        self.instruments[marginRate.InstrumentID].marginrate = (marginRate.LongMarginRatioByMoney,marginRate.ShortMarginRatioByMoney)
        #print str(marginRate)
        self.check_qry_commands()

    def rsp_qry_trading_account(self,account):
        '''
            查询资金帐户回报
        '''
        self.available = account.Available
        self.check_qry_commands()        
    
    def rsp_qry_instrument(self,pinstrument):
        '''
            获得合约数量乘数. 
            这里的保证金率应该是和期货公司无关，所以不能使用
        '''
        if pinstrument.InstrumentID not in self.instruments:
            self.logger.warning(u'收到未监控的合约查询:%s' % (pinstrument.InstrumentID))
            return
        self.instruments[pinstrument.InstrumentID].multiple = pinstrument.VolumeMultiple
        self.instruments[pinstrument.InstrumentID].tick_base = int(pinstrument.PriceTick * 10 + 0.1)
        self.check_qry_commands()

    def rsp_qry_position_detail(self,position_detail):
        '''
            查询持仓明细回报, 得到每一次成交的持仓,其中若已经平仓,则持量为0,平仓量>=1
            必须忽略
        '''
        print str(position_detail)
        self.check_qry_commands()

    def rsp_qry_order(self,sorder):
        '''
            查询报单
            可以忽略
        '''
        self.check_qry_commands()

    def rsp_qry_trade(self,strade):
        '''
            查询成交
            可以忽略
        '''
        self.check_qry_commands()


class SaveAgent(Agent):
    def init_init(self):
        Agent.init_init(self)
        self.save_flag = True

    def RtnTick(self,ctick):#行情处理主循环
        inst = ctick.instrument
        if inst not in self.instruments:
            logger.info(u'接收到未订阅的合约数据:%s' % (inst,))
        dinst = self.instruments[inst]#.data
        self.prepare_base(dinst,ctick)  
    
    def rsp_qry_instrument(self,pinstrument):
        '''
            获得合约名称
        '''
        if pinstrument.InstrumentID not in self.instruments:
            self.instruments[pinstrument.InstrumentID] = c_instrument(pinstrument.InstrumentID)


def make_user(my_agent,hq_user,name='data'):
    user = MdApi.CreateMdApi(name)
    #print my_agent.instruments
    user.RegisterSpi(MdSpiDelegate(instruments=my_agent.instruments, 
                             broker_id=hq_user.broker_id,
                             investor_id= hq_user.investor_id,
                             passwd= hq_user.passwd,
                             agent = my_agent,
                    ))
    user.RegisterFront(hq_user.port)
    
    user.Init()


def save_raw(base_name='base.ini',strategy_name='strategy.ini',base='Base',strategy='strategy'):
    '''
        按配置文件给定的绝对合约名保存
        只用到MdUser
        base_name是保存base设置的文件名
        strategy_name是保存strategy设置的文件名

    '''
    logging.basicConfig(filename="ctp_user_agent.log",level=logging.DEBUG,format='%(name)s:%(funcName)s:%(lineno)d:%(asctime)s %(levelname)s %(message)s')
 
    base_cfg = config.parse_base(base_name,base)
    strategy_cfg = config.parse_strategy(strategy_name,strategy)
 
    my_insts = strategy_cfg.traces_raw

    my_agent = SaveAgent(None,None,my_insts,{})
    
    for user in base_cfg.users:
        make_user(my_agent,base_cfg.users[user],user)

    #获取合约列表
    return my_agent

def save_raw2():
    return save_raw(base_name='mybase.ini')


def save(base_name='base.ini',strategy_name='strategy.ini',base='Base',strategy='strategy'): 
    '''
        根据配置文件给定的合约类型，查找所有合约，然后保存
        用到了User和Trader
    '''
    logging.basicConfig(filename="ctp_user_agent.log",level=logging.DEBUG,format='%(name)s:%(funcName)s:%(lineno)d:%(asctime)s %(levelname)s %(message)s')
 
    cfg = config.parse_base(base_name,base)
 
    ctrader = cfg.traders.values()[0]
    trader = TraderApi.CreateTraderApi(ctrader.name)
    t_agent = SaveAgent(trader,ctrader,[],{})
    
    myspi = TraderSpiDelegate(instruments=t_agent.instruments, 
                             broker_id=ctrader.broker_id,
                             investor_id= ctrader.investor_id,
                             passwd= ctrader.passwd,
                             agent = t_agent,
                       )
    trader.RegisterSpi(myspi)
    trader.SubscribePublicTopic(THOST_TERT_QUICK)
    trader.SubscribePrivateTopic(THOST_TERT_QUICK)
    trader.RegisterFront(ctrader.port)
    trader.Init()
    
    strategy_cfg = config.parse_strategy(strategy_name,strategy)
    
    time.sleep(20)
    #print strategy_cfg.traces
    for tin in strategy_cfg.traces:
        print tin
        t_agent.fetch_instrument(tin)
        time.sleep(30)

    #for user in cfg.users:
    #    make_user(my_agent,cfg.users[user],user)

    #获取合约列表
    return t_agent

def save2():
    return save(base_name='mybase.ini')


def trade_test_main(name='base.ini',base='Base'):
    '''
import agent
trader,myagent = agent.trade_test_main()
#开仓

##释放连接
trader.RegisterSpi(None)
    '''
    logging.basicConfig(filename="ctp_trade.log",level=logging.DEBUG,format='%(name)s:%(funcName)s:%(lineno)d:%(asctime)s %(levelname)s %(message)s')
    
    trader = TraderApi.CreateTraderApi("trader")

    cfg = config.parse_base(name,base)

    cuser = cfg.traders.values()[0]
    
    #cuser = c.SQ_TRADER2
    my_agent = Agent(trader,cuser,INSTS,{})
    myspi = TraderSpiDelegate(instruments=my_agent.instruments, 
                             broker_id=cuser.broker_id,
                             investor_id= cuser.investor_id,
                             passwd= cuser.passwd,
                             agent = my_agent,
                       )
    trader.RegisterSpi(myspi)
    trader.SubscribePublicTopic(THOST_TERT_QUICK)
    trader.SubscribePrivateTopic(THOST_TERT_QUICK)
    trader.RegisterFront(cuser.port)
    trader.Init()
    return trader,my_agent
    
'''
#测试
import agent
trader,myagent = agent.trade_test_main()

myagent.spi.OnRspOrderInsert(agent.BaseObject(OrderRef='12',InstrumentID='IF1103'),agent.BaseObject(ErrorID=1,ErrorMsg='test'),1,1)
myagent.spi.OnErrRtnOrderInsert(agent.BaseObject(OrderRef='12',InstrumentID='IF1103'),agent.BaseObject(ErrorID=1,ErrorMsg='test'))
myagent.spi.OnRspOrderAction(agent.BaseObject(OrderRef='12',InstrumentID='IF1103'),agent.BaseObject(ErrorID=1,ErrorMsg='test'),1,1)
myagent.spi.OnErrRtnOrderAction(agent.BaseObject(OrderRef='12',InstrumentID='IF1103'),agent.BaseObject(ErrorID=1,ErrorMsg='test'))

#资金和持仓
myagent.fetch_trading_account()
myagent.fetch_investor_position(u'IF1104')
myagent.fetch_instrument_marginrate(u'IF1104')
myagent.fetch_instrument(u'IF1104')
#myagent.fetch_investor_position_detail(u'IF1104')


#测试报单
morder = agent.BaseObject(instrument='IF1103',direction='0',order_ref=myagent.inc_order_ref(),price=3280,volume=1)
myagent.open_position(morder)
morder = agent.BaseObject(instrument='IF1103',direction='0',order_ref=myagent.inc_order_ref(),price=3280,volume=20)

#平仓
corder = agent.BaseObject(instrument='IF1103',direction='1',order_ref=myagent.inc_order_ref(),price=3220,volume=1)
myagent.close_position(corder)

#测试撤单
import agent
trader,myagent = agent.trade_test_main()

cref = myagent.inc_order_ref()
morder = agent.BaseObject(instrument='IF1104',direction='0',order_ref=cref,price=3180,volume=1)
myagent.open_position(morder)

rorder = agent.BaseObject(instrument='IF1103',order_ref=cref)
myagent.cancel_command(rorder)


'''


if __name__=="__main__":
    main()